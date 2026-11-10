import os
import sys

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    ExecuteProcess,
    LogInfo,
    OpaqueFunction,
    RegisterEventHandler,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration

try:  # installed package
    from mobilevit_uav_pipeline.run_log import publisher_csv_path, resolve_output_csv, resolve_run_id
except ImportError:  # checked-in launch file executed from the repository root
    sys.path.insert(
        0,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mobilevit_uav_pipeline'),
    )
    from run_log import publisher_csv_path, resolve_output_csv, resolve_run_id

PUBLISHER_SCRIPT = 'src/ros2_uav_pipeline/mobilevit_uav_pipeline/image_stream_node.py'
DETECTOR_SCRIPT = 'src/ros2_uav_pipeline/mobilevit_uav_pipeline/mobilevit_detector_node.py'

# model_name selects the timm model; weights are random-init (pretrained=False).
# There is deliberately no model_path argument: no checkpoint file is loaded.
REMOVED_ARGUMENTS = {
    'model_path': 'model_path is not supported: the detector creates the timm model named by '
                  'model_name with random weights (pretrained=False) and loads no weight file.',
}

ARGUMENTS = [
    ('dataset_path', 'data/raw/images/coco128/images/train2017'),
    ('input_fps', '30.0'),
    ('qos_depth', '10'),
    ('model_name', 'mobilevit_xxs'),
    ('fake_inference_delay_ms', '0'),
    ('deadline_ms', '100.0'),
    ('resource_profile', 'normal'),
    ('scenario', 'fps_sweep'),
    # 'auto' = 產生唯一 run_id，寫入 results/raw/ros2/<run_id>.csv（不 append）。
    ('output_csv', 'auto'),
    ('run_id', 'auto'),
    ('warmup_frames', '10'),
    # Phase 3 / Batch 1 application scheduling (detector only). legacy_qos = Phase 2 behaviour.
    ('scheduler_policy', 'legacy_qos'),
    ('queue_capacity', '5'),
    ('fifo_overflow', 'reject_newest'),
    ('adaptive_window', '32'),
    ('adaptive_quantile', '0.9'),
    ('adaptive_margin_ms', '0.0'),
    ('adaptive_overload_threshold', '1.0'),
    ('intra_op_threads', '0'),
]
SCHEDULER_ARGUMENTS = [
    'scheduler_policy', 'queue_capacity', 'fifo_overflow', 'adaptive_window',
    'adaptive_quantile', 'adaptive_margin_ms', 'adaptive_overload_threshold', 'intra_op_threads',
]


def _node_process(script, name, params):
    cmd = ['python3', script, '--ros-args']
    for key, value in params:
        cmd += ['-p', f'{key}:={value}']
    return ExecuteProcess(cmd=cmd, name=name, output='screen')


def _launch_setup(context, *args, **kwargs):
    for name, reason in REMOVED_ARGUMENTS.items():
        if name in context.launch_configurations:
            # An ignored argument would make the run look like it used that setting.
            raise RuntimeError(reason)
    value = {name: LaunchConfiguration(name).perform(context) for name, _ in ARGUMENTS}
    # run_id 只在這裡解析一次，publisher 與 detector 共用同一個 run_id。
    run_id = resolve_run_id(value['run_id'])
    detector_csv = resolve_output_csv(value['output_csv'], run_id)

    publisher = _node_process(PUBLISHER_SCRIPT, 'image_stream_node', [
        ('dataset_path', value['dataset_path']),
        ('input_fps', value['input_fps']),
        ('run_id', run_id),
        ('output_csv', publisher_csv_path(detector_csv)),
    ])
    detector = _node_process(DETECTOR_SCRIPT, 'mobilevit_detector_node', [
        ('model_name', value['model_name']),
        ('input_fps', value['input_fps']),
        ('qos_depth', value['qos_depth']),
        ('fake_inference_delay_ms', value['fake_inference_delay_ms']),
        ('deadline_ms', value['deadline_ms']),
        ('scenario', value['scenario']),
        ('resource_profile', value['resource_profile']),
        ('output_csv', detector_csv),
        ('run_id', run_id),
        ('warmup_frames', value['warmup_frames']),
        *[(name, value[name]) for name in SCHEDULER_ARGUMENTS],
    ])

    # 任一 node 結束（啟動失敗、例外或被停止）就結束整個 launch，
    # 不再讓另一個 node 空轉到 timeout；呼叫端以「是否撐到 timeout」判斷成功與否。
    shutdown_on_exit = [
        RegisterEventHandler(OnProcessExit(
            target_action=process,
            on_exit=[
                LogInfo(msg=f'{label} exited; shutting down run {run_id}.'),
                EmitEvent(event=Shutdown(reason=f'{label} exited')),
            ],
        ))
        for process, label in ((detector, 'mobilevit_detector_node'), (publisher, 'image_stream_node'))
    ]
    return [publisher, detector, *shutdown_on_exit]


def generate_launch_description():
    return LaunchDescription([
        *[DeclareLaunchArgument(name, default_value=default) for name, default in ARGUMENTS],
        OpaqueFunction(function=_launch_setup),
    ])
