# -*- coding: utf-8 -*-
from setuptools import setup, find_packages

PKG_NAME = 'ssh_proxy'
PKG = __import__(PKG_NAME)


setup(
    name=PKG_NAME,
    version=PKG.__version__,
    description='',
    author='Noble Code',
    maintainer='Andrey Ovchinnikov',
    maintainer_email='andrey@noblecode.ru',
    packages=find_packages(),
    install_requires=[
        'AWSIoTPythonSDK~=1.2.0',
        'docker',
        'msgpack-python',
    ],
    entry_points={
        'console_scripts': [
            'ssh-proxy = ssh_proxy.__main__:main',
        ],
    },
)
