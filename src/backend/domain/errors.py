class AppError(Exception):
    def __init__(self, message: str, code: str = 'invalid_input', status: int = 422):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


class NotFound(AppError):
    def __init__(self, message: str = 'Задание или файл не найден'):
        super().__init__(message, 'not_found', 404)


class RevisionConflict(AppError):
    def __init__(self):
        super().__init__('Задание изменилось, обновите ответы', 'revision_conflict', 409)


class OperationCancelled(AppError):
    def __init__(self):
        super().__init__('Операция остановлена или версия задания изменилась', 'cancelled', 409)
