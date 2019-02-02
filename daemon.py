# Copyright (C) 2017 DataArt
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import cv2
import json
import time
import thread
import threading
import datetime
import logging.config
from Tkinter import *
from devicehive_webconfig import Server, Handler

from subprocedure_sequence import demo_instruments
from models.yolo import Yolo2Model
from utils.general import format_predictions, extrap_instrument, format_data, format_person_prediction
from web.routes import routes
from log_config import LOGGING

logging.config.dictConfig(LOGGING)

logger = logging.getLogger('detector')



class Sequencer():

    def __init__(self):
        self.last_instruments=None
        self.sequence = []

    def getSequence(self):
        return self.sequence

    def update(self, instruments_in_use, time_delta):
        if len(self.sequence) == 0:
            # segment = Segment(instruments_in_use, time_delta)
            segment = {
                "instruments": instruments_in_use,
                "time": time_delta
            }
            self.last_instruments = instruments_in_use
            self.sequence.append(segment)
            return

        print(self.sequence[-1])
        updated_time = self.sequence[-1]["time"] + time_delta
        self.sequence[-1]["time"] = updated_time
        print(self.sequence[-1]["time"])

        if self.last_instruments != instruments_in_use:
            # segment = Segment(instruments_in_use, 0.0)
            segment = {
                "instruments": instruments_in_use,
                "time": 0.0
            }
            self.last_instruments = instruments_in_use
            self.sequence.append(segment)
        return

    def pruneSequence(self):
        if len(self.sequence) <= 4:
            return
        # newSequence = []
        removeList = []
        for i in range(len(self.sequence)):
            if i != len(self.sequence) - 1:
                segment = self.sequence[i]
                if segment["time"] < 5.0:
                    removeList.append(segment)
        for segment in removeList:
            self.sequence.remove(segment)
        return
    


    def printSequence(self):
        print("Print Sequence: ", self.sequence)
        return
    


class calculator():
    def __init__(self):
        self.last_time_stamp = None
        self.instrument_minutes =age = {}
        self.timesplits = {}
        self.delta = None

    def update(self, frame):
        current = datetime.datetime.now().isoformat()
        
        if (self.last_time_stamp != None):
            self.delta = current - self.last_time_stamp
            self.delta.total_minutes()
            print("TOTAL MINUTES: ", self.delta)


class DeviceHiveHandler(Handler):

    _device = None
    surgery_meta = None
    _payload = None
    instruments_in_use = None
    op_instr = None

    last_time_stamp = None
    total_seconds = 0.0
    instrument_seconds = 0.0
    instruments_usage = {}
    timesplits = {}
    delta = None
    sequencer = Sequencer()

    # def __init__(self):
    #     self.instruments_in_use = None

    def handle_connect(self):
        # self.calculator = calculator()
        

        self._device = self.api.put_device(self._device_id)
        super(DeviceHiveHandler, self).handle_connect()

    

    def send(self, data):
        print("BEFORE: ", data)
        global dead
        # print(data)
        if type(data)!=list:
            self._device.send_notification("instruments", {"notification":data})
        elif not dead:
            confidence, self.op_instr = extrap_instrument(data, self.instruments_in_use)
            print("AFTER: ", self.op_instr)
            
            self.update_frame(self.op_instr)
            sequence = self.sequencer.getSequence()

            data = format_data(self.surgery_meta, self.op_instr, confidence, self.instruments_usage, sequence)

            self._device.send_notification("instruments", {"notification":data})

    def set_instr(self, instruments_in_use):
        self.instruments_in_use = instruments_in_use

        for instrument in self.instruments_in_use:
            self.instruments_usage[instrument] = 0.0

    def get_op_instr(self):
        return self.op_instr

    def set_meta(self, meta):
        self.surgery_meta = meta

    # def __datetime(self, date_str):
    #     return datetime.datetime.strptime(date_str, '%a %b %d %H:%M:%S +0000 %Y')

    def update_frame(self, frame):
        print("YEAR: ", datetime.time())
        if self.last_time_stamp == None:
            self.last_time_stamp = datetime.datetime.now()
            return 

        current = datetime.datetime.now()
        print("TIME: ", current)
        self.delta = current - self.last_time_stamp
        diff = self.delta.seconds
        diff += round((self.delta.microseconds /1e6),3)
        self.total_seconds += diff
        print(self.delta.microseconds)
        print("TOTAL MINUTES: ", (self.total_seconds))
        self.last_time_stamp = current

        print("FRAME: ", frame)
        for instrument in frame:
            try:
                self.instruments_usage[instrument] += diff
                self.instrument_seconds += diff
            except:
                print("Inferred Instrument that is not in use in the surgery")

        for key in self.instruments_usage:
            print("INSTRUMENT: ", key)
            print("time used: ", self.instruments_usage[key])
            print(self.instrument_seconds)
            try:
                self.timesplits[key] = self.instruments_usage[key] / self.instrument_seconds
            except:
                print("no instruments used yet")

        self.sequencer.update(frame, diff)
        self.sequencer.pruneSequence()
        print("BIGGER SHABINGER: ")
        self.sequencer.printSequence()
        print("BIG SHABANG: ", self.timesplits)
        
 
class Daemon(Server):
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, cv2.COLOR_LUV2LBGR]

    _detect_frame_data = None
    _detect_frame_data_id = None
    _cam_thread = None

    # sequencer = Sequencer()
    

    def __init__(self, *args, **kwargs):
        super(Daemon, self).__init__(*args, **kwargs)
        self._detect_frame_data_id = 0
        self._cam_thread = threading.Thread(target=self._cam_loop, name='cam')
        self._cam_thread.setDaemon(True)
        # self.op_instr = None

    def _on_startup(self):
        self._cam_thread.start()

    def _cam_loop(self):
        logger.info('Start camera loop')
        cam = cv2.VideoCapture(1)
        if not cam.isOpened():
            raise IOError('Can\'t open "{}"'.format(0))

        source_h = cam.get(cv2.CAP_PROP_FRAME_HEIGHT)
        source_w = cam.get(cv2.CAP_PROP_FRAME_WIDTH)

        model = Yolo2Model(input_shape=(source_h, source_w, 3))
        model.init()

        start_time = time.time()
        frame_num = 0
        fps = 0

        global dead
        try:
            while self.is_running and not dead:
                ret, frame = cam.read()

                if not ret:
                    logger.warning('Can\'t read video data')
                    continue

                predictions = model.evaluate(frame)

                for o in predictions:
                    x1 = o['box']['left']
                    x2 = o['box']['right']

                    y1 = o['box']['top']
                    y2 = o['box']['bottom']

                    color = o['color']
                    class_name = o['class_name']

                    # Draw box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                    # Draw label
                    (test_width, text_height), baseline = cv2.getTextSize(
                        class_name, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 1)
                    cv2.rectangle(frame, (x1, y1),
                                  (x1+test_width, y1-text_height-baseline),
                                  color, thickness=cv2.FILLED)
                    cv2.putText(frame, class_name, (x1, y1-baseline),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 1)

                end_time = time.time()
                fps = fps * 0.9 + 1/(end_time - start_time) * 0.1
                start_time = end_time

                # Draw additional info
                frame_info = 'Frame: {0}, FPS: {1:.2f}'.format(frame_num, fps)
                cv2.putText(frame, frame_info, (10, frame.shape[0]-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                logger.info(frame_info)

                self._detect_frame_data_id = frame_num
                _, img = cv2.imencode('.jpg', frame, self.encode_params)
                self._detect_frame_data = img

                if predictions:
                    formatted = format_predictions(predictions)
                    logger.info('Predictions: {}'.format(formatted))
                    self._send_dh(predictions)

                frame_num += 1

        finally:
            print("cam released")
            cam.release()
            model.close()

    def _send_dh(self, data):
        global dead
        # set information about the surgery
        if not self.dh_status.connected:
            logger.error('Devicehive is not connected')
            return
        if dead and type(data)==list:
            print("Last frame not sent")
            return

        # self.op_instr = data
        # print("OP_INSTR: ", op_instr)
        self.deviceHive.handler.send(data)

    def get_frame(self):
        return self._detect_frame_data, self._detect_frame_data_id

 


class Widget(Daemon):
    

    def __init__(self, daemon):
        self.server = daemon


        self.window = Tk()
        self.window.title("Assist-MD Capture")
        self.window.geometry('500x400')

        self.hospital_field = "Saint Judes"
        self.doctor_field = "Brian Humphreys"
        self.patient_field = "David Roster"
        self.procedure_field = "Appendectomy2"
        self.instrument_packets_field = 1

        self.hospital_lbl = Label(self.window, text="Hospital Name: ")
        self.hospital_lbl.grid(column=0, row=0)
        v = StringVar(self.window, value=self.hospital_field)
        self.hospital_txt = Entry(self.window,textvariable=v,width=20)
        self.hospital_txt.grid(column=1, row=0)

        self.doctor_lbl = Label(self.window, text="Doctor's Name: ")
        self.doctor_lbl.grid(column=0, row=1)
        v = StringVar(self.window, value=self.doctor_field)
        self.doctor_txt = Entry(self.window,textvariable=v,width=20)
        self.doctor_txt.grid(column=1, row=1)

        self.patient_lbl = Label(self.window, text="Patient's Name: ")
        self.patient_lbl.grid(column=0, row=2)
        v = StringVar(self.window, value=self.patient_field)
        self.patient_txt = Entry(self.window,textvariable=v,width=20)
        self.patient_txt.grid(column=1, row=2)

        self.procedure_lbl = Label(self.window, text="Procedure: ")
        self.procedure_lbl.grid(column=0, row=3)
        v = StringVar(self.window, value=self.procedure_field)
        self.procedure_txt = Entry(self.window,textvariable=v,width=20)
        self.procedure_txt.grid(column=1, row=3)

        self.instruments_lbl = Label(self.window, text="Number of Packets: ")
        self.instruments_lbl.grid(column=0, row=4)
        v = StringVar(self.window, value=self.instrument_packets_field)
        self.instruments_txt = Entry(self.window,textvariable=v,width=20)
        self.instruments_txt.grid(column=1, row=4)

        self.radiovar = IntVar()

        self.demo1_lbl = Label(self.window, text="Instrument set 1: ")
        self.demo1_lbl.grid(column=0, row=6)
        self.demo1_chk = Radiobutton(
            self.window, 
            text="Option 1", 
            variable=self.radiovar, 
            value=1,
            command=self.checkBoxClicked)
        self.demo1_chk.grid(column=1, row=6)

        self.demo2_lbl = Label(self.window, text="Instrument set 2: ")
        self.demo2_lbl.grid(column=0, row=7)
        self.demo2_chk = Radiobutton(
            self.window, 
            text="Option 2", 
            variable=self.radiovar, 
            value=2,
            command=self.checkBoxClicked)
        self.demo2_chk.grid(column=1, row=7)

        self.demo3_lbl = Label(self.window, text="Instrument set 3: ")
        self.demo3_lbl.grid(column=0, row=8)
        self.demo3_chk = Radiobutton(
            self.window, 
            text="Option 3", 
            variable=self.radiovar, 
            value=3,
            command=self.checkBoxClicked)
        self.demo3_chk.grid(column=1, row=8)

        self.startButtonState = ACTIVE
        self.stopButtonState = DISABLED
        
        self.start_btn = Button(
            self.window, 
            text="Start Capture", 
            command=self.startClicked,
            state=self.startButtonState)
        self.start_btn.grid(column=2, row=0)

        self.stop_btn = Button(
            self.window, 
            text="Stop Capture", 
            command=self.stopClicked,
            state=self.stopButtonState)
        self.stop_btn.grid(column=2, row=1)

        self.instru_lbl = Label(self.window, text="Instrument In Use: ")
        self.instru_lbl.grid(column=0, row=9)
        self.instruments_in_use_box = Text(self.window, height=6, width=20)
        self.instruments_in_use_box.grid(column=0, row=10)
        self.instruments_in_use = None

        self.oper_lbl = Label(self.window, text="Instrument In Dr's Hand: ")
        self.oper_lbl.grid(column=1, row=9)
        self.operating_instruments_box = Text(self.window, height=6, width=20)
        self.operating_instruments_box.grid(column=1, row=10)
        
    def startClicked(self):
        print("starting server")
        self.hospital_field = self.hospital_txt.get()
        self.doctor_field = self.doctor_txt.get()
        self.patient_field = self.patient_txt.get()
        self.procedure_field = self.procedure_txt.get()
        self.instrument_packets_field = self.instruments_txt.get()

        meta = {
            "hospital": self.hospital_field,
            "doctor": self.doctor_field,
            "patient": self.patient_field,
            "procedure": self.procedure_field,
            "packets": self.instrument_packets_field
        }
    

        self.stop_btn["state"] = ACTIVE
        self.start_btn["state"] = DISABLED

        self.server.start()
        # self.server = Daemon(DeviceHiveHandler, routes=routes, is_blocking=False)
        # self._server_thread = threading.Thread(target=self.server.start, name='run-server')
        # self._server_thread.start()
        # thread.start_new_thread( self.server.start() )

        while not self.server.dh_status.connected:
            # Wait till DH connection is ready
            time.sleep(.001)


        self.server.deviceHive.handler.set_instr(self.instruments_in_use)
        self.server.deviceHive.handler.set_meta(meta)
        self._server_loop_thread = threading.Thread(target=self._server_loop, name='server-loop')
        self._server_loop_thread.start()
        
    def _server_loop(self):
        global dead 
        
        while self.server.dh_status.connected and not dead:
            # Wait till DH connection is ready
            time.sleep(1)
            self.op_instr = self.server.deviceHive.handler.get_op_instr()
            print("GREAT: ", self.op_instr)
            try:
                self.operating_instruments_box.delete('1.0', END)
                for instrument in self.op_instr:
                    self.operating_instruments_box.insert(END, instrument + '\n')
            except:
                print("waiting for operating instrument inference")

    def stopClicked(self):
        global dead 
        dead = True
        self.stop_btn["state"] = DISABLED
        self.start_btn["state"] = ACTIVE
        print('stop clicked')
        time.sleep(1)
        self.server._send_dh({"type": "end"})
        
        print("FUCK OFF")
        self.server.stop()
        self.window.destroy()

    def checkBoxClicked(self):
        self.instruments_in_use = demo_instruments["instruments"][self.radiovar.get()-1]
        print("The instruments are: ", self.instruments_in_use)

        self.instruments_in_use_box.delete('1.0', END)
        for instrument in self.instruments_in_use:
            self.instruments_in_use_box.insert(END, instrument + '\n')
            print(instrument)
        
    def create_widget(self):
        self.window.mainloop()

if __name__ == '__main__':
    global dead
    dead = False
    server = Daemon(DeviceHiveHandler, routes=routes, is_blocking=False)
    
    prog = Widget(server)
    prog.create_widget()

    # widget_thread = threading.Thread(target=prog.create_widget, name='run-ui')
    # widget_thread.start()
    
