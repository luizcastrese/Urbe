class AppError(Exception):
    def __init__(self, message, status=400, code="APP_ERROR"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code

