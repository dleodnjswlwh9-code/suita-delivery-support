# Single worker is required because in-memory async job state is process-local.
# gthread allows polling while long MILP computation runs in a background thread.
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 180
graceful_timeout = 30
