#!/usr/bin/env python
from setuptools import setup, find_packages
 
 
setup(
    name='gevent-erlangmode',
    url='https://github.com/miracle2k/gevent-erlang-mode',
    license='BSD',
    version='0.0.1',
    packages=find_packages(),
    zip_safe=False,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
