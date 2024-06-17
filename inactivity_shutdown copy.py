import time
from flask import request

def check_inactivity_and_shutdown(last_request_time, shutdown_threshold=1800):  # Default 30 minutes
    """
    Monitors for inactivity and shuts down the Flask server if the threshold is exceeded.
    
    Args:
        last_request_time: A shared mutable object (like a list) that stores the last request time.
        shutdown_threshold: Time in seconds to wait before shutting down the server due to inactivity.
    """
    while True:
        time.sleep(60)  # Check every 60 seconds
        if time.time() - last_request_time[0] > shutdown_threshold:
            print("Shutting down the server due to inactivity.")
            shutdown_server()
            break

def shutdown_server():
    """
    Shuts down the Flask server gracefully.
    """
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running within a Werkzeug Server')
    func()
