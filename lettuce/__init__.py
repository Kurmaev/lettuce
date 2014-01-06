# -*- coding: utf-8 -*-
# <Lettuce - Behaviour Driven Development for python>
# Copyright (C) <2010-2012>  Gabriel Falcão <gabriel@nacaolivre.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__version__ = version = '0.2.19'

release = 'kryptonite'

import os
import csv
import os.path
import sys
import signal
import traceback
import multiprocessing

from datetime import datetime

try:
    from imp import reload
except ImportError:
    # python 2.5 fallback
    pass

import random
import itertools

from lettuce.core import Feature, TotalResult, FeatureResult

from lettuce.terrain import after
from lettuce.terrain import before
from lettuce.terrain import world

from lettuce.decorators import step, steps
from lettuce.registry import call_hook
from lettuce.registry import STEP_REGISTRY
from lettuce.registry import CALLBACK_REGISTRY
from lettuce.exceptions import StepLoadingError
from lettuce.plugins import (
    xunit_output,
    subunit_output,
    autopdb,
    smtp_mail_queue,
)
from lettuce import fs
from lettuce import exceptions

try:
    from colorama import init as ms_windows_workaround
    ms_windows_workaround()
except ImportError:
    pass


__all__ = [
    'after',
    'before',
    'step',
    'steps',
    'world',
    'STEP_REGISTRY',
    'CALLBACK_REGISTRY',
    'call_hook',
]

try:
    terrain = fs.FileSystem._import("terrain")
    reload(terrain)
except Exception, e:
    if not "No module named terrain" in str(e):
        string = 'Lettuce has tried to load the conventional environment ' \
            'module "terrain"\nbut it has errors, check its contents and ' \
            'try to run lettuce again.\n\nOriginal traceback below:\n\n'

        sys.stderr.write(string)
        sys.stderr.write(exceptions.traceback.format_exc(e))
        raise SystemExit(1)


class Runner(object):
    """ Main lettuce's test runner

    Takes a base path as parameter (string), so that it can look for
    features and step definitions on there.
    """
    def __init__(self, base_path, scenarios=None, verbosity=0, random=False,
                 enable_xunit=False, xunit_filename=None,
                 enable_subunit=False, subunit_filename=None,
                 tags=None, failfast=False, auto_pdb=False,
                 smtp_queue=None):

        """ lettuce.Runner will try to find a terrain.py file and
        import it from within `base_path`
        """
        self.tags = tags
        self.single_feature = None

        if os.path.isfile(base_path) and os.path.exists(base_path):
            self.single_feature = base_path
            base_path = os.path.dirname(base_path)

        sys.path.insert(0, base_path)
        self.loader = fs.FeatureLoader(base_path)
        self.verbosity = verbosity
        self.scenarios = scenarios and map(int, scenarios.split(",")) or None
        self.failfast = failfast
        if auto_pdb:
            autopdb.enable(self)

        sys.path.remove(base_path)

        if verbosity is 0:
            from lettuce.plugins import non_verbose as output
        elif verbosity is 1:
            from lettuce.plugins import dots as output
        elif verbosity is 2:
            from lettuce.plugins import scenario_names as output
        elif verbosity is 3:
            from lettuce.plugins import shell_output as output
        else:
            from lettuce.plugins import colored_shell_output as output

        self.random = random

        if enable_xunit:
            xunit_output.enable(filename=xunit_filename)
        if smtp_queue:
            smtp_mail_queue.enable()

        if enable_subunit:
            subunit_output.enable(filename=subunit_filename)

        reload(output)

        self.output = output

    def run(self):
        """ Find and load step definitions, and them find and load
        features under `base_path` specified on constructor
        """
        try:
            self.loader.find_and_load_step_definitions()
        except StepLoadingError, e:
            print "Error loading step definitions:\n", e
            return

        results = []
        if self.single_feature:
            features_files = [self.single_feature]
        else:
            features_files = self.loader.find_feature_files()
            if self.random:
                random.shuffle(features_files)

        if not features_files:
            self.output.print_no_features_found(self.loader.base_dir)
            return

        world.port_number = 8181
        call_hook('before', 'all')
        call_hook('before', 'batch')
        begin_time = datetime.utcnow()


        failed = False
        try:
            for filename in features_files:
                feature = Feature.from_file(filename)
                results.append(
                    feature.run(self.scenarios,
                                tags=self.tags,
                                random=self.random,
                                failfast=self.failfast))

        except exceptions.LettuceSyntaxError, e:
            sys.stderr.write(e.msg)
            failed = True
        except:
            if not self.failfast:
                e = sys.exc_info()[1]
                print "Died with %s" % str(e)
                traceback.print_exc()
            else:
                print
                print ("Lettuce aborted running any more tests "
                       "because was called with the `--failfast` option")

            failed = True

        finally:
            total_time = datetime.utcnow() - begin_time
            total = TotalResult(results, total_time)
            call_hook('after', 'batch')
            call_hook('after', 'all', total)

            if failed:
                raise SystemExit(2)

            return total


class ParallelRunner(Runner):

    def __init__(self, base_path, scenarios=None, verbosity=0, random=False,
                 enable_xunit=False, xunit_filename=None,
                 enable_subunit=False, subunit_filename=None,
                 tags=None, failfast=False, auto_pdb=False,
                 smtp_queue=None,workers=None):

        super(ParallelRunner, self).__init__( base_path,
                                              scenarios=scenarios,
                                              verbosity=verbosity,
                                              random=random,
                                              enable_xunit=enable_xunit,
                                              xunit_filename=xunit_filename,
                                              enable_subunit=enable_subunit,
                                              subunit_filename=subunit_filename,
                                              failfast=failfast,
                                              auto_pdb=auto_pdb,
                                              tags=tags)


        self.workers = workers



    def run(self):
        """ Find and load step definitions, and them find and load
        features under `base_path` specified on constructor
        """
        begin_time = datetime.utcnow()
        try:
            self.loader.find_and_load_step_definitions()
        except StepLoadingError, e:
            print "Error loading step definitions:\n", e
            return

        if self.single_feature:
            features_files = [self.single_feature]
        else:
            features_files = self.loader.find_feature_files()
            if self.random:
                random.shuffle(features_files)

        if not features_files:
            self.output.print_no_features_found(self.loader.base_dir)
            return

        manager = multiprocessing.Manager()
        errors = manager.list()
        results = manager.list()

        failed = False
        scenarios_to_run = []
        try:

            for filename in features_files:
                feature = Feature.from_file(filename)
                feature_scenarios_to_run = feature.scenarios_to_run(self.scenarios,self.tags)
                scenarios_to_run.extend(feature_scenarios_to_run)
        except exceptions.LettuceSyntaxError, e:
            sys.stderr.write(e.msg)
            failed = True


        # sort scenarios in slowest to fastest by looking at the last run time if existed
        if os.path.isfile('.scenarios.csv'):
            scenario_metas = csv.DictReader(open(".scenarios.csv"))
            name_duration_dict = dict()
            for scenario_meta in scenario_metas:
                name_duration_dict[scenario_meta['name']] = scenario_meta['duration']

            scenario_duration_dict = dict()
            for scenario in scenarios_to_run:
                if scenario.name in name_duration_dict:
                    scenario_duration_dict[scenario] = name_duration_dict[scenario.name]
                else:
                    scenario_duration_dict[scenario] = 0

            # now sort them:
            sorted_tupples = sorted(scenario_duration_dict.items(), key=lambda x: -int(x[1]))
            scenarios_to_run = [tupple[0] for tupple in sorted_tupples]


        scenario_queue = multiprocessing.Queue()
        for s in scenarios_to_run:
            scenario_queue.put(s)


        call_hook('before', 'all')

        ignore_case = True

        def process_scenarios(scenario_queue,port_number,results,errors):
            #print "running batch with port number: {}".format(port_number)
            world.port_number = port_number

            call_hook('before', 'batch')

            while not scenario_queue.empty():

                try:
                    scenario_to_execute = scenario_queue.get()
                    result = scenario_to_execute.run(ignore_case, failfast=self.failfast)

                    import pickle
                    failed = False
                    try:
                        pickle.dumps(result)
                    except Exception as e:
                        print "Failed: [{}]".format(e)
                        traceback.print_exc()
                        failed = True

                    if failed:
                        print "!!!!! Failed to pickle: {}".format(scenario_to_execute.name)

                    results.append(result)

                except Exception as e:
                    if not self.failfast:
                        e = sys.exc_info()[1]
                        print "Died with %s" % str(e)
                        traceback.print_exc()
                        errors.append(e)
                    else:
                        print
                        print ("Lettuce aborted running any more tests "
                               "because was called with the `--failfast` option")

            call_hook('after','batch')

        # TODO use pool
        processes = []
        for i in xrange(self.workers):
            port_number = 8180 + i
            process = multiprocessing.Process(target=process_scenarios,args=(scenario_queue,port_number,results,errors))
            processes.append(process)
            process.start()

        try:
            for process in processes:
                process.join()
        except (KeyboardInterrupt, SystemExit):
            print "Ctr-C processed shutting down"
            for process in processes:
                process.terminate()
                process.join()

            print "trying to exit!"
            sys.exit(0)


        if len(errors) > 0:
            print "Exceptions"
            for error in errors:
                print error
        else:
            print "Test suite had no errors"

            feature_results = []

            for feature, scenario_results in itertools.groupby(results, lambda r: r[0].scenario.feature):
                all_results = []
                for results in scenario_results:
                    for result in results:
                        all_results.append(result)

                feature_results.append(FeatureResult(feature, *list(all_results)))

            time_elapsed = datetime.utcnow() - begin_time

            total = TotalResult(feature_results, time_elapsed)
            total.persist_to_csv()

            call_hook('after', 'all', total)

            if failed:
                raise SystemExit(2)

            return total


