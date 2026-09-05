# Phase 3: CommentCrawler — Tài liệu Kỹ thuật

## Tóm tắt thay đổi

Tạo mới file `crawlers/comment.py` (602 dòng) — trích xuất toàn bộ logic comment crawling và metrics extraction từ `crawler.py` (Facade) sang domain crawler riêng biệt theo pattern **Delegation (ch36)** + **Constructor Injection (ch35)**.

`crawler.py` giảm từ 1463 → 1031 dòng (~430 dòng code logic chuyển sang `comment.py`).

## Mục đích & Ý nghĩa

### Vấn đề giải quyết
Comment crawling + metrics extraction chiếm ~430 dòng logic phức tạp trong monolith `crawler.py`. Các method này bao gồm:
- GraphQL comment pagination (bi-directional)
- Reply fetching
- Comment template synthesis
- HTML metrics extraction (reaction_count, comment_count)
- GraphQL metrics parsing
- Post metrics DB update

Gộp chung với group feed crawling vi phạm **SRP** (Single Responsibility Principle) — một class đảm nhận cả feed crawling lẫn comment/metrics.

### Thiết kế

```
FacebookCrawler (Facade)
├── CrawlerEngine (HTTP infra)
├── GroupCrawler (group feed)
└── CommentCrawler (comment + metrics)  ← NEW
```

`CommentCrawler` HAS-A `CrawlerEngine` (Composition via Constructor Injection). Facade `FacebookCrawler` giữ thin delegation methods để backward compatibility.

## Các method đã di chuyển

| Method cũ (Facade) | Method mới (CommentCrawler) | Loại |
|---|---|---|
| `_extract_feedback_ids` | `extract_feedback_ids` | Static |
| `_extract_comment_page_info` | `extract_comment_page_info` | Static |
| `_parse_comment_ids` | `parse_comment_ids` | Static |
| `extract_metrics_from_html` | `extract_metrics_from_html` | Static |
| `_parse_metrics_from_graphql` | `parse_metrics_from_graphql` | Static |
| `_fetch_comments` | `fetch_comments` | Instance (async) |
| `_fetch_replies` | `fetch_replies` | Instance (async) |
| `_synthesize_comment_template` | `synthesize_comment_template` | Instance |
| `_update_post_metrics` | `update_post_metrics` | Instance |
| `_find_comment_ids` (module-level) | `find_comment_ids` (module-level) | Pure function |

## Mối liên hệ

### File bị ảnh hưởng
- **`crawler.py`** (Facade): 10 method refactored thành thin delegation wrappers
- **`crawlers/__init__.py`**: Thêm export `CommentCrawler`
- **`crawlers/comment.py`**: File mới — chứa toàn bộ comment & metrics logic

### Backward Compatibility
- `FacebookCrawler.extract_metrics_from_html(html)` vẫn hoạt động (delegate sang `CommentCrawler`)
- `FacebookCrawler._parse_metrics_from_graphql(resp_text)` vẫn hoạt động
- Module-level `_find_comment_ids(obj)` vẫn hoạt động (delegate sang `find_comment_ids`)
- Tất cả test hiện có (59/59) pass không cần sửa đổi

### Dependencies
- `CrawlerEngine` (Phase 1) — HTTP infrastructure
- `SessionStateManager` — GraphQL session state (vẫn nằm ở Facade, truyền vào qua parameter)
- `DataHelper` — JSON extraction utilities
- `extract_from_responses` — Comment data persistence

## Rủi ro (Risks & Edge Cases)

1. **SessionStateManager coupling**: `_comment_session_state` vẫn nằm ở `FacebookCrawler` (Facade) và được truyền qua parameter vào `fetch_comments`/`fetch_replies`. Đây là design chủ đích — SessionState quản lý dynamic tokens liên tục thay đổi, phải singleton per-crawler instance.

2. **Static method delegation overhead**: Các static methods (`extract_metrics_from_html`, etc.) giờ qua thêm 1 layer indirection. Performance impact negligible vì bottleneck là network I/O, không phải function call overhead.

3. **`_fetch_comments_for_page` vẫn ở Facade**: Method này orchestrate comment + reply fetching cho một page response. Nó gọi `CommentCrawler.extract_feedback_ids`, `self._comment.fetch_comments`, `self._comment.fetch_replies` — vẫn nằm ở Facade vì nó phụ thuộc vào `self._stopped_comment_posts` state. Có thể di chuyển sau nếu cần.

4. **`_execute_crawl_comments` và `_scrape_comments_from_page`**: Hai method lớn này (~200 dòng) vẫn ở Facade vì phụ thuộc nặng vào Facade state (`_comment_progress`, `_stopped_comment_posts`, `_comment_worker_task`). Chúng sẽ được refactor khi tách worker logic (nếu cần).
