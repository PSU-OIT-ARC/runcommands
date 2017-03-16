from locale import getpreferredencoding
from threading import Thread


class NonBlockingStreamReader(Thread):

    def __init__(self, name, stream, buffer, hide, file, encoding=None):
        name = '{name}-reader'.format(name=name)
        super().__init__(name=name, daemon=True)
        self.stream = stream
        self.buffer = buffer
        self.hide = hide
        self.file = file
        self.encoding = encoding or getpreferredencoding(do_setlocale=False)
        self.start()

    def run(self):
        while not self.stream.closed:
            try:
                data = self.stream.readline()
            except ValueError:
                break
            if data:
                if isinstance(data, bytes):
                    text = data.decode(self.encoding)
                else:
                    text = data
                self.buffer.append(text)
                if not self.hide:
                    self.file.write(text)
                    self.file.flush()

    def get_string(self):
        return ''.join(self.buffer)