from .exceptions import *
from .utils import *
import logging
import time
from datetime import datetime

class Alias(object):
    def __init__(self, alias=None):
        """
        Define the Alias object.

        :arg alias: The alias name
        """
        if not alias:
            raise MissingArgument('No value for "alias" provided.')
        #: The alias name.  Also accessible as an instance variable.
        self.alias = alias
        #: The list of actions to perform.  Populated by
        #: :mod:`curator.actions.Alias.add` and
        #: :mod:`curator.actions.Alias.remove`
        self.actions = []
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client  = None
        self.loggit  = logging.getLogger('curator.actions.alias')

    def add(self, ilo):
        """
        Create `add` statements for each index in `ilo` for `alias`, then
        append them to `actions`.

        :arg ilo: A :class:`curator.indexlist.IndexList` object

        """
        verify_index_list(ilo)
        if not self.client:
            self.client = ilo.client
        ilo.empty_list_check()
        for index in ilo.working_list():
            self.loggit.debug(
                'Adding index {0} to alias {1}'.format(index, self.alias))
            self.actions.append(
                { 'add' : { 'index' : index, 'alias': self.alias } })

    def remove(self, ilo):
        """
        Create `remove` statements for each index in `ilo` for `alias`,
        then append them to `actions`.

        :arg ilo: A :class:`curator.indexlist.IndexList` object
        """
        verify_index_list(ilo)
        if not self.client:
            self.client = ilo.client
        ilo.empty_list_check()
        for index in ilo.working_list():
            self.loggit.debug(
                'Removing index {0} from alias {1}'.format(index, self.alias))
            self.actions.append(
                { 'remove' : { 'index' : index, 'alias': self.alias } })

    def body(self):
        """
        Return a `body` string suitable for use with the `update_aliases` API
        call.
        """
        if not self.actions:
            raise ActionError('No "add" or "remove" operations')
        self.loggit.debug('Alias actions: {0}'.format(self.actions))

        return { 'actions' : self.actions }

    def do_action(self):
        """
        Run the API call `update_aliases` with the results of `body()`
        """
        self.loggit.info('Updating aliases...')
        try:
            self.client.indices.update_aliases(body=self.body())
        except Exception as e:
            report_failure(e)

class Allocation(object):
    def __init__(self, ilo, key=None, value=None, allocation_type='require'):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        :arg key: An arbitrary metadata attribute key.  Must match the key
            assigned to at least some of your nodes to have any effect.
        :arg value: An arbitrary metadata attribute value.  Must correspond to
            values associated with `key` assigned to at least some of your nodes
            to have any effect.
        :arg allocation_type: Type of allocation to apply. Default is `require`

        .. note::
            See:
            https://www.elastic.co/guide/en/elasticsearch/reference/current/shard-allocation-filtering.html
        """
        verify_index_list(ilo)
        if not key:
            raise MissingArgument('No value for "key" provided')
        if not value:
            raise MissingArgument('No value for "value" provided')
        if allocation_type not in ['require', 'include', 'exclude']:
            raise ValueError(
                '{0} is an invalid allocation_type.  Must be one of "require", '
                '"include", "exclude".'.format(allocation_type)
            )
        #: Instance variable.
        #: Internal reference to `ilo`
        self.index_list = ilo
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client     = ilo.client
        self.loggit     = logging.getLogger('curator.actions.allocation')
        #: Instance variable.
        #: Populated at instance creation time. Value is
        #: ``index.routing.allocation.`` `allocation_type` ``.`` `key` ``.`` `value`
        self.body       = (
            'index.routing.allocation.'
            '{0}.{1}={2}'.format(allocation_type, key, value)
        )

    def do_action(self):
        """
        Change allocation settings for indices in `index_list.indices` with the
        settings in `body`.
        """
        self.loggit.info(
            'Cannot get change shard routing allocation of closed indices.  '
            'Omitting any closed indices.'
        )
        self.index_list.filter_closed()
        self.index_list.empty_list_check()

        self.loggit.info('Updating index setting {0}'.format(self.body))
        try:
            index_lists = chunk_index_list(self.index_list.indices)
            for l in index_lists:
                self.client.indices.put_settings(
                    index=to_csv(l), body=self.body
                )
        except Exception as e:
            report_failure(e)

class Close(object):
    def __init__(self, ilo):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        """
        verify_index_list(ilo)
        #: Instance variable.
        #: Internal reference to `ilo`
        self.index_list = ilo
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client     = ilo.client
        self.loggit     = logging.getLogger('curator.actions.close')

    def do_action(self):
        """
        Close open indices in `index_list.indices`
        """
        self.index_list.filter_closed()
        self.index_list.empty_list_check()
        self.loggit.info('Closing selected indices')
        try:
            index_lists = chunk_index_list(self.index_list.indices)
            for l in index_lists:
                # Do sync_flush from SyncFlush object after it's built?
                self.client.indices.flush(
                    index=to_csv(l), ignore_unavailable=True)
                self.client.indices.close(
                    index=to_csv(l), ignore_unavailable=True)
        except Exception as e:
            report_failure(e)

class DeleteIndices(object):
    def __init__(self, ilo, master_timeout=30):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        :arg master_timeout: Number of seconds to wait for master node response
        """
        verify_index_list(ilo)
        if not type(master_timeout) == type(int()):
            raise TypeError(
                'Incorrect type for "master_timeout": {0}. '
                'Should be integer value.'.format(type(master_timeout))
            )
        #: Instance variable.
        #: Internal reference to `ilo`
        self.index_list     = ilo
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client         = ilo.client
        #: Instance variable.
        #: String value of `master_timeout` + 's', for seconds.
        self.master_timeout = str(master_timeout) + 's'
        self.loggit         = logging.getLogger('curator.actions.delete_indices')
        self.loggit.debug('master_timeout value: {0}'.format(
            self.master_timeout))

    def _verify_result(self, result, count):
        """
        Breakout method to aid readability
        :arg result: A list of indices from `_get_result_list`
        :arg count: The number of tries that have occurred
        :rtype: bool
        """
        if len(result) > 0:
            self.loggit.error(
                'The following indices failed to delete on try '
                '#{0}:'.format(count)
            )
            for idx in result:
                self.loggit.error("---{0}".format(idx))
            return False
        else:
            self.loggit.debug(
                'Successfully deleted all indices on try #{0}'.format(count)
            )
            return True

    def __chunk_loop(self, chunk_list):
        """
        Loop through deletes 3 times to ensure they complete
        :arg chunk_list: A list of indices pre-chunked so it won't overload the
            URL size limit.
        """
        working_list = chunk_list
        for count in range(1, 4): # Try 3 times
            for i in working_list:
                self.loggit.info("---deleting index {0}".format(i))
            self.client.indices.delete(
                index=to_csv(working_list), master_timeout=self.master_timeout)
            result = [ i for i in working_list if i in get_indices(self.client)]
            if self._verify_result(result, count):
                return
            else:
                working_list = result
        self.loggit.error(
            'Unable to delete the following indices after 3 attempts: '
            '{0}'.format(result)
        )

    def do_action(self):
        """
        Delete indices in `index_list.indices`
        """
        self.index_list.empty_list_check()
        self.loggit.info('Deleting selected indices')
        try:
            index_lists = chunk_index_list(self.index_list.indices)
            for l in index_lists:
                self.__chunk_loop(l)
        except Exception as e:
            report_failure(e)

class ForceMerge(object):
    def __init__(self, ilo, max_num_segments=None, delay=0):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        :arg max_num_segments: Number of segments per shard to forceMerge
        :arg delay: Number of seconds to delay between forceMerge operations
        """
        verify_index_list(ilo)
        if not max_num_segments:
            raise MissingArgument('Missing value for "max_num_segments"')
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client = ilo.client
        #: Instance variable.
        #: Internal reference to `ilo`
        self.index_list = ilo
        #: Instance variable.
        #: Internally accessible copy of `max_num_segments`
        self.max_num_segments = max_num_segments
        #: Instance variable.
        #: Internally accessible copy of `delay`
        self.delay = delay
        self.loggit = logging.getLogger('curator.actions.forcemerge')

    def do_action(self):
        """
        forcemerge indices in `index_list.indices`
        """
        self.index_list.empty_list_check()
        self.index_list.filter_forceMerged(
            max_num_segments=self.max_num_segments)
        self.loggit.info('forceMerging selected indices')
        try:
            for index_name in self.index_list.indices:
                self.loggit.info(
                    'forceMerging index {0} to {1} segments per shard.  '
                    'Please wait...'.format(index_name, self.max_num_segments)
                )
                self.client.indices.forcemerge(
                    index=index_name, max_num_segments=self.max_num_segments)
                if self.delay > 0:
                    self.loggit.info(
                        'Pausing for {0} seconds before continuing...'.format(
                            self.delay)
                    )
                    time.sleep(self.delay)
        except Exception as e:
            report_failure(e)

class Open(object):
    def __init__(self, ilo):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        """
        verify_index_list(ilo)
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client     = ilo.client
        #: Instance variable.
        #: Internal reference to `ilo`
        self.index_list = ilo
        self.loggit     = logging.getLogger('curator.actions.open')

    def do_action(self):
        """
        Open closed indices in `index_list.indices`
        """
        self.index_list.empty_list_check()
        self.loggit.info('Opening selected indices')
        try:
            index_lists = chunk_index_list(self.index_list.indices)
            for l in index_lists:
                self.client.indices.open(index=to_csv(l))
        except Exception as e:
            report_failure(e)

class Replicas(object):
    def __init__(self, ilo, count=None):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        :arg count: The count of replicas per shard
        """
        verify_index_list(ilo)
        # It's okay for count to be zero
        if count == 0:
            pass
        elif not count:
            raise MissingArgument('Missing value for "count"')
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client     = ilo.client
        #: Instance variable.
        #: Internal reference to `ilo`
        self.index_list = ilo
        #: Instance variable.
        #: Internally accessible copy of `count`
        self.count      = count
        self.loggit     = logging.getLogger('curator.actions.replicas')

    def do_action(self):
        """
        Update the replica count of indices in `index_list.indices`
        """
        self.index_list.empty_list_check()
        self.loggit.info(
            'Cannot get update replica count of closed indices.  '
            'Omitting any closed indices.'
        )
        self.index_list.filter_closed()
        self.loggit.info(
            'Updating the replica count of selected indices to '
            '{0}'.format(self.count)
        )
        try:
            index_lists = chunk_index_list(self.index_list.indices)
            for l in index_lists:
                self.client.indices.put_settings(index=to_csv(l),
                    body='number_of_replicas={0}'.format(self.count))
        except Exception as e:
            report_failure(e)

class DeleteSnapshots(object):
    def __init__(self, slo, retry_interval=120, retry_count=3):
        """
        :arg slo: A :class:`curator.snapshotlist.SnapshotList` object
        :arg retry_interval: Number of seconds to delay betwen retries. Default:
            120 (seconds)
        :arg retry_count: Number of attempts to make. Default: 3
        """
        verify_snapshot_list(slo)
        #: Instance variable.
        #: The Elasticsearch Client object derived from `slo`
        self.client         = slo.client
        #: Instance variable.
        #: Internally accessible copy of `retry_interval`
        self.retry_interval = retry_interval
        #: Instance variable.
        #: Internally accessible copy of `retry_count`
        self.retry_count    = retry_count
        #: Instance variable.
        #: Internal reference to `slo`
        self.snapshot_list  = slo
        #: Instance variable.
        #: The repository name derived from `slo`
        self.repository     = slo.repository
        self.loggit = logging.getLogger('curator.actions.delete_snapshots')

    def do_action(self):
        """
        Delete snapshots in `slo`
        Retry up to `retry_count` times, pausing `retry_interval`
        seconds between retries.
        """
        self.snapshot_list.empty_list_check()
        self.loggit.info('Deleting selected snapshots')
        if not safe_to_snap(
            self.client, repository=self.repository,
            retry_interval=self.retry_interval, retry_count=self.retry_count):
                raise FailedExecution(
                    'Unable to delete snapshot(s) because a snapshot is in '
                    'state "IN_PROGRESS"')
        try:
            for s in self.snapshot_list.snapshots:
                self.loggit.info('Deleting snapshot {0}...'.format(s))
                self.client.snapshot.delete(
                    repository=self.repository, snapshot=s)
        except Exception as e:
            report_failure(e)

class Snapshot(object):
    def __init__(self, ilo, repository=None, name=None,
                ignore_unavailable=False, include_global_state=True,
                partial=False, wait_for_completion=True,
                skip_repo_fs_check=False):
        """
        :arg ilo: A :class:`curator.indexlist.IndexList` object
        :arg repository: The Elasticsearch snapshot repository to use
        :arg name: What to name the snapshot.
        :arg wait_for_completion: Wait (or not) for the operation
            to complete before returning.  (default: `True`)
        :type wait_for_completion: bool
        :arg ignore_unavailable: Ignore unavailable shards/indices.
            (default: `False`)
        :type ignore_unavailable: bool
        :arg include_global_state: Store cluster global state with snapshot.
            (default: `True`)
        :type include_global_state: bool
        :arg partial: Do not fail if primary shard is unavailable. (default:
            `False`)
        :type partial: bool
        :arg skip_repo_fs_check: Do not validate write access to repository on
            all cluster nodes before proceeding. (default: `False`).  Useful for
            shared filesystems where intermittent timeouts can affect
            validation, but won't likely affect snapshot success.
        :type skip_repo_fs_check: bool
        """
        verify_index_list(ilo)
        if not repository_exists(ilo.client, repository=repository):
            raise ActionError(
                'Cannot snapshot indices to missing repository: '
                '{0}'.format(repository)
            )
        if not name:
            raise MissingArgument('No value for "name" provided.')
        #: Instance variable.
        #: The parsed version of `name`
        self.name = parse_snapshot_name(name)
        #: Instance variable.
        #: The Elasticsearch Client object derived from `ilo`
        self.client              = ilo.client
        #: Instance variable.
        #: Internally accessible copy of `repository`
        self.repository          = repository
        #: Instance variable.
        #: Internally accessible copy of `wait_for_completion`
        self.wait_for_completion = wait_for_completion
        #: Instance variable.
        #: Internally accessible copy of `skip_repo_fs_check`
        self.skip_repo_fs_check  = skip_repo_fs_check
        self.state               = None
        #: Instance variable.
        #: Populated at instance creation time by calling
        #: :mod:`curator.utils.create_snapshot_body` with `ilo.indices` and the
        #: provided arguments: `ignore_unavailable`, `include_global_state`,
        #: `partial`
        self.body                = create_snapshot_body(
                ilo.indices,
                ignore_unavailable=ignore_unavailable,
                include_global_state=include_global_state,
                partial=partial
            )

        self.loggit = logging.getLogger('curator.actions.snapshot')

    def get_state(self):
        """
        Get the state of the snapshot
        """
        try:
            self.state = self.client.snapshot.get(
                repository=self.repository,
                snapshot=self.name)['snapshots'][0]['state']
            return self.state
        except IndexError:
            raise CuratorException(
                'Snapshot "{0}" not found in repository '
                '"{1}"'.format(self.name, self.repository)
            )

    def report_state(self):
        """
        Log the state of the snapshot
        """
        self.get_state()
        if self.state == 'SUCCESS':
            self.loggit.info(
                'Snapshot {0} successfully completed.'.format(self.name))
        else:
            self.loggit.warn(
                'Snapshot {0} completed with state: {0}'.format(self.state))

    def do_action(self):
        """
        Snapshot indices in `index_list.indices`, with options passed.
        """
        if not self.skip_repo_fs_check:
            test_repo_fs(self.client, self.repository)
        if snapshot_running(self.client):
            raise SnapshotInProgress('Snapshot already in progress.')
        try:
            self.client.snapshot.create(
                repository=self.repository, snapshot=self.name, body=self.body,
                wait_for_completion=self.wait_for_completion
            )
            if self.wait_for_completion:
                self.report_state()
            else:
                self.loggit.warn(
                    '"wait_for_completion" set to {0}. '
                    'Remember to check for successful completion '
                    'manually.'.format(self.wait_for_completion)
                )
        except Exception as e:
            report_failure(e)