"""Console progress without a second database connection or SQL/answer logging."""
from threading import Event, Lock, Thread
from time import monotonic


class RefreshProgress:
    def __init__(self, stream, interval=15):
        self.stream, self.interval = stream, interval
        self.started = monotonic()
        self.stage = 'เริ่มดำเนินการ'
        self.completed = 0
        self.query_started = None
        self.last_return = self.started
        self.mutex, self.stop = Lock(), Event()

    def _write(self, message):
        elapsed = int(monotonic()-self.started)
        self.stream.write(f'[{elapsed//60:02}:{elapsed%60:02}] {message}')
        self.stream.flush()

    def __call__(self, message):
        with self.mutex:
            self.stage = message
            self._write(message)

    def query(self, execute, sql, params, many, context):
        with self.mutex:
            self.query_started = monotonic()
        try:
            result = execute(sql, params, many, context)
        except BaseException:
            with self.mutex:
                self.query_started = None
            raise
        else:
            with self.mutex:
                self.completed += 1
                self.last_return = monotonic()
                self.query_started = None
            return result

    def report(self):
        with self.mutex:
            now = monotonic()
            if self.query_started is not None:
                detail = f'รอคำสั่งฐานข้อมูลปัจจุบัน {int(now-self.query_started)} วินาที'
            else:
                detail = f'นอกคำสั่งฐานข้อมูล; คำสั่งล่าสุดจบเมื่อ {int(now-self.last_return)} วินาทีก่อน'
            self._write(f'ยังไม่เสร็จ — {self.stage} | คำสั่งฐานข้อมูลจบแล้ว {self.completed:,} | {detail}')

    def _watch(self):
        while not self.stop.wait(self.interval):
            self.report()

    def __enter__(self):
        self.thread = Thread(target=self._watch, name='refresh-progress', daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=2)
