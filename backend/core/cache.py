# core/cache.py

# user_id를 키로, 최신 탐지 결과를 값으로 저장하는 인메모리 캐시
# {
#   "user_id_1": { "status": "processed", "objects": [...], ... },
#   "user_id_2": { ... }
# }
latest_detection_results: dict = {}
