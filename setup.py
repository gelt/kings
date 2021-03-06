from setuptools import setup, find_packages

setup(
    name = 'kings',
    version = '0.0.1',
    license = 'MIT',
    description = open('README.md').read(),
    author = 'Carlo Cabanilla',
    author_email = 'carlo.cabanilla@gmail.com',
    url = 'https://github.com/clofresh/kings',
    platforms = 'any',
    packages = find_packages(),
    package_data={'kings': ['content/*.yaml']},
    zip_safe = True,
    verbose = False,
    install_requires=[
        'distribute>=0.6.0',
        'gevent>=0.13.6',
        'pyyaml>=3.0',
    ],
    entry_points={'console_scripts': ['kings = kings.__main__:main']}
)

