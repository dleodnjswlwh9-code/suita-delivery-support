# 非同期処理の状態はプロセスごとに保持するため、作業プロセスを1つとする。計算中の状態照会はスレッドで受け付ける。
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 180
graceful_timeout = 30
