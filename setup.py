from setuptools import setup

# Read long_description from file
try:
    long_description = open('README.rst', 'rb').read()
except:
    long_description = ('Please see https://github.com/adamancer/pyncei.git'
                        ' for more information about pyncei.')

setup(name='pyncei',
      version='0.1',
      description='Python bindings for NOAA\'s National Centers'
                  ' for Environomental Information webservices',
      long_description=long_description,
      classifiers = [
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.7'
      ],
      url='https://github.com/adamancer/pyncei.git',
      author='adamancer',
      author_email='mansura@si.edu',
      license='MIT',
      packages=['pyncei'],
      install_requires = [
          'lxml',
          'requests',
          'requests_cache'
      ],
      include_package_data=True,
      zip_safe=False)
