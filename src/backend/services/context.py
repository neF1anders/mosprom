"""Bounded partitioning of source text without dropping coverage."""


def source_batches(sources: dict, max_chars: int = 10000):
    """Linear partition with overlap-free coverage; each source retains its identity."""
    batch: dict = {}
    size = 0
    image_count = 0
    for key, source in sources.items():
        text = source["text"]
        for start in range(0, max(1, len(text)), max_chars):
            piece = {**source, "text": text[start : start + max_chars]}
            if batch and (
                size + len(piece["text"]) > max_chars or (piece.get("image") and image_count >= 3)
            ):
                yield batch
                batch, size, image_count = {}, 0, 0
            if key in batch:
                yield batch
                batch, size, image_count = {}, 0, 0
            batch[key] = piece
            size += len(piece["text"])
            image_count += bool(piece.get("image"))
    if batch:
        yield batch
