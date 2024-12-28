# import tracemalloc

# def start_memory_tracking():
#     tracemalloc.start()

# def print_top_allocations(limit=10):
#     snapshot = tracemalloc.take_snapshot()
#     top_stats = snapshot.statistics('lineno')
#     print("[ Top memory allocations ]")
#     for stat in top_stats[:limit]:
#         print(stat)

