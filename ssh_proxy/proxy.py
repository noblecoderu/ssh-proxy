#from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import signal
import threading


class Proxy:
    def __init__(self):
        self._stop = threading.Event()

    def run_forever(self):
        try:
            self._stop.wait()
        except:
            print('Got exception')
        else:
            print('No exception')

    def catch_signals(self):
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        self._stop.set()


proxy = Proxy()
proxy.catch_signals()
proxy.run_forever()
