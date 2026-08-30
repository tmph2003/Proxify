import pytest

class CrawlerState:
    def __init__(self, start_timestamp: int):
        self.start_timestamp = start_timestamp
        self.consecutive_old_pages = 0

    def process_page(self, timestamps: list[int]) -> bool:
        """
        Returns True if the crawler should STOP, False otherwise.
        """
        if not timestamps:
            return False

        old_posts = [t for t in timestamps if t < self.start_timestamp]
        if len(old_posts) == len(timestamps):
            self.consecutive_old_pages += 1
        else:
            self.consecutive_old_pages = 0
            
        return self.consecutive_old_pages >= 2


def test_start_date_less_than_post_date():
    state = CrawlerState(100)
    assert not state.process_page([110, 120])
    assert not state.process_page([150])

def test_post_date_equals_start_date():
    state = CrawlerState(100)
    assert not state.process_page([100, 100])

def test_post_date_less_than_start_date():
    state = CrawlerState(100)
    assert not state.process_page([90, 80]) # Page 1: old posts, counter = 1
    assert state.process_page([70, 60])    # Page 2: old posts, counter = 2 -> STOP!

def test_multiple_posts_across_boundary():
    state = CrawlerState(100)
    assert not state.process_page([110, 90]) # Mixed page, counter = 0
    assert not state.process_page([105])     # New posts, counter = 0
    assert not state.process_page([90, 80])  # Old posts, counter = 1
    assert not state.process_page([110])     # Pinned/New post, counter = 0 (reset!)
    assert not state.process_page([80, 70])  # Old posts, counter = 1
    assert state.process_page([60])          # Old posts, counter = 2 -> STOP!

def test_missing_date():
    state = CrawlerState(100)
    assert not state.process_page([])
    assert not state.process_page([]) # Missing dates shouldn't trigger stop

def test_invalid_date_range_validation():
    # Validation happens at API layer, but here we just test state robustness
    state = CrawlerState(200)
    assert not state.process_page([300]) # Valid new post
    assert not state.process_page([150]) # Page 1 old
    assert state.process_page([100])     # Page 2 old -> STOP
