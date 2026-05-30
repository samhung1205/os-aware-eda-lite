from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration
import os

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('dataset_path', default_value='data/raw/images/coco128/images/train2017'),
        DeclareLaunchArgument('input_fps', default_value='30.0'),
        DeclareLaunchArgument('qos_depth', default_value='10'),
        DeclareLaunchArgument('model_path', default_value='mobilevit_xxs'),
        DeclareLaunchArgument('model_name', default_value='mobilevit_xxs'),
        DeclareLaunchArgument('fake_inference_delay_ms', default_value='0'),
        DeclareLaunchArgument('deadline_ms', default_value='100.0'),
        DeclareLaunchArgument('resource_profile', default_value='normal'),
        DeclareLaunchArgument('scenario', default_value='fps_sweep'),
        DeclareLaunchArgument('output_csv', default_value='results/raw/ros2/latency_log.csv'),

        ExecuteProcess(
            cmd=[
                'python3', 'src/ros2_uav_pipeline/mobilevit_uav_pipeline/image_stream_node.py',
                '--ros-args',
                '-p', ['dataset_path:=', LaunchConfiguration('dataset_path')],
                '-p', ['input_fps:=', LaunchConfiguration('input_fps')]
            ],
            output='screen'
        ),
        
        ExecuteProcess(
            cmd=[
                'python3', 'src/ros2_uav_pipeline/mobilevit_uav_pipeline/mobilevit_detector_node.py',
                '--ros-args',
                '-p', ['model_name:=', LaunchConfiguration('model_name')],
                '-p', ['input_fps:=', LaunchConfiguration('input_fps')],
                '-p', ['qos_depth:=', LaunchConfiguration('qos_depth')],
                '-p', ['fake_inference_delay_ms:=', LaunchConfiguration('fake_inference_delay_ms')],
                '-p', ['deadline_ms:=', LaunchConfiguration('deadline_ms')],
                '-p', ['scenario:=', LaunchConfiguration('scenario')],
                '-p', ['resource_profile:=', LaunchConfiguration('resource_profile')],
                '-p', ['output_csv:=', LaunchConfiguration('output_csv')]
            ],
            output='screen'
        )
    ])
