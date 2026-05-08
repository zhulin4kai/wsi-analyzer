class OOMRetryPolicy:
    @staticmethod
    def is_oom(error: RuntimeError) -> bool:
        text = str(error).lower()
        return any(keyword in text for keyword in ("out of memory", "oom", "memory"))

    @staticmethod
    def next_batch_size(current: int) -> int:
        return max(1, current // 2)
