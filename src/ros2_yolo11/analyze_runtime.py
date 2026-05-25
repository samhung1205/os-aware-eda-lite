"""Legacy compatibility entry point for the generic ROS2 runtime analyzer."""

from src.ros2_runtime.analyze_runtime import *  # noqa: F403
from src.ros2_runtime.analyze_runtime import main


if __name__ == "__main__":
    main()
