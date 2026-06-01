from setuptools import setup
import os
from glob import glob

package_name = 'mobilevit_uav_pipeline'

setup(
    name=package_name,
    version='0.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=[
        'setuptools',
        'numpy<2.0.0',
        'opencv-python',
        'psutil',
        'timm',
        'torch',
    ],
    zip_safe=True,
    maintainer='emo',
    maintainer_email='emo@example.com',
    description='ROS 2 UAV pipeline for MobileViT simulation',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'image_stream_node = mobilevit_uav_pipeline.image_stream_node:main',
            'mobilevit_detector_node = mobilevit_uav_pipeline.mobilevit_detector_node:main'
        ],
    },
)
