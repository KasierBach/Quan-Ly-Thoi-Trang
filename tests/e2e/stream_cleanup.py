class CloseOnExhaustion:
    """Test-server wrapper closes aborted streamed files without buffering content."""

    def __init__(self, iterable):
        self.iterable = iterable
        self.iterator = iter(iterable)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self.iterator)
        except BaseException:
            self.close()
            raise

    def close(self):
        if not self.closed:
            self.closed = True
            close = getattr(self.iterable, 'close', None)
            if close is not None:
                close()

    def __del__(self):
        self.close()
