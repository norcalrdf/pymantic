from setuptools import setup

from pymantic import version

tests_require = [
    'betamax',
    ]

testing_extras = tests_require + [
    'nose',
    'coverage',
    ]

from io import open
f = open('README.rst', mode='r', encoding='utf8')


setup(name='pymantic',
      version=version,
      description="Semantic Web and RDF library for Python",
      long_description=f.read(),
      classifiers=[
          'Development Status :: 3 - Alpha',
          'Intended Audience :: Developers',
          'License :: OSI Approved :: BSD License',
          'Topic :: Internet :: WWW/HTTP',
          'Topic :: Scientific/Engineering :: Information Analysis',
          'Topic :: Text Processing :: Markup',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
      ],  # Get strings from http://pypi.python.org/pypi?%3Aaction=list_classifiers
      keywords='RDF N3 Turtle Semantics Web3.0',
      author='Gavin Carothers, Nick Pilon',
      author_email='gavin@carothers.name, npilon@gmail.com',
      url='https://github.com/norcalrdf/pymantic/',
      license='BSD',
      packages=['pymantic'],
      include_package_data=True,
      zip_safe=False,
      test_suite='nose.collector',
      install_requires=[
          'requests',
          'lxml',
          'pytz',
          'rdflib',
          'lepl',
          ],
      extras_require={
          'testing': testing_extras,
          },
      entry_points="""
      # -*- Entry points: -*-
      """,
      scripts=[
          'pymantic/scripts/named_graph_to_nquads',
          'pymantic/scripts/bnf2html',
      ])
