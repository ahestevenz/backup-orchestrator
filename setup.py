from setuptools import setup, find_packages


def readme():
    with open('README.rst') as f:
        return f.read()

setup(  name='bnBackupModule',
        version='0.1.0b1',
        description='Backup based on RSYNC command',
        packages=find_packages('src'),
        package_dir={'': 'src'},
        long_description=readme(),
        classifiers=[
            'Development Status :: 3 - Alpha',
	        'Programming Language :: Python :: 3',
            'Intended Audience :: Developers',
        ],
        keywords='backup sync rsync',
        url='https://github.com/ahestevenz/ll',
        author='Ariel Hernandez <ariel.h.estevenz@ieee.org>',
        author_email='ariel.h.estevenz@ieee.org',
        license='Proprietary',
        install_requires=[
            'numpy', 'pexpect', 'shutil'
        ],
        test_suite='nose.collector',
        tests_require=['nose'],
        entry_points = {
            'console_scripts': ['bn-run-backup=bnBackupModule.scripts.run_backup:main',
            ],
        },
        include_package_data=True,
        zip_safe=True
    )
