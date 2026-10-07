"""CLI failures must remain fail-closed and carry useful bounded evidence."""
import json
import subprocess
from unittest.mock import Mock

import pytest

from simulation.px4_gazebo import gazebo_evidence as evidence


def result(monkeypatch, code=0, stdout='', stderr=''):
    run = Mock(return_value=subprocess.CompletedProcess([], code, stdout, stderr))
    monkeypatch.setattr(evidence.subprocess, 'run', run)
    return run


@pytest.mark.parametrize('code,expected_signal', [(1, None), (-11, 'SIGSEGV'), (-15, 'SIGTERM')])
@pytest.mark.parametrize('stdout', ['', '{"pose":[]}'])
def test_nonzero_exit_is_rejected_even_with_valid_json_and_empty_stderr(monkeypatch, code, expected_signal, stdout):
    run = result(monkeypatch, code, stdout)
    with pytest.raises(ValueError, match='gazebo_pose_probe_failed:') as caught:
        evidence.capture_poses('test_world', .25)
    diagnostic = json.loads(str(caught.value).split(':', 1)[1])
    assert diagnostic['returncode'] == code
    assert diagnostic['signal'] == expected_signal
    assert diagnostic['stdout_bytes'] == len(stdout.encode())
    assert diagnostic['stderr_bytes'] == 0
    assert diagnostic['topic'] == '/world/test_world/dynamic_pose/info'
    assert diagnostic['stage'] == 'exit'
    assert diagnostic['wall_elapsed_s'] >= 0
    assert diagnostic['duration_s'] == .25
    assert diagnostic['timeout_s'] == 5.25
    assert diagnostic['source_timestamp']
    assert run.call_count == (2 if code == -11 else 1)
    if code == -11:
        assert diagnostic['attempt'] == 2
        assert diagnostic['previous_failures'][0]['returncode'] == -11


def test_timeout_keeps_partial_bytes_without_inventing_a_returncode(monkeypatch):
    run = Mock(side_effect=subprocess.TimeoutExpired(['gz'], 5.25, output=b'{"pose":', stderr=b'warning'))
    monkeypatch.setattr(evidence.subprocess, 'run', run)
    with pytest.raises(TimeoutError, match='gazebo_pose_probe_timeout:') as caught:
        evidence.capture_poses('test_world', .25)
    diagnostic = json.loads(str(caught.value).split(':', 1)[1])
    assert diagnostic['returncode'] is None
    assert diagnostic['stage'] == 'timeout'
    assert diagnostic['stdout_bytes'] == 8
    assert diagnostic['stderr_tail'] == 'warning'


def test_large_output_is_bounded_but_byte_count_is_complete(monkeypatch):
    result(monkeypatch, 1, 'x' * 100_000, 'warning' * 10_000)
    with pytest.raises(ValueError) as caught:
        evidence.capture_poses('test_world', .25)
    diagnostic = json.loads(str(caught.value).split(':', 1)[1])
    assert diagnostic['stdout_bytes'] == 100_000
    assert diagnostic['stderr_bytes'] == 70_000
    assert len(diagnostic['stdout_tail']) == 512
    assert len(diagnostic['stderr_tail']) == 512
    assert len(str(caught.value)) < 2000


def test_parse_failure_is_distinct_and_does_not_drop_truncated_object(monkeypatch):
    result(monkeypatch, stdout='{"pose":[]} {"pose":')
    with pytest.raises(ValueError, match='gazebo_pose_probe_parse_failed:') as caught:
        evidence.capture_poses('test_world', .25)
    assert '"stage": "parse"' in str(caught.value)
    assert '"returncode": 0' in str(caught.value)


def test_success_keeps_concatenated_json_support(monkeypatch):
    run = result(monkeypatch, stdout='{"pose":[]} {"pose":[{"id":1}]}')
    assert evidence.capture_poses('test_world', .25) == [{'pose': []}, {'pose': [{'id': 1}]}]
    assert 0 < run.call_args.kwargs['timeout'] <= 5.25


def test_missing_executable_has_start_stage(monkeypatch):
    monkeypatch.setattr(evidence.subprocess, 'run', Mock(side_effect=FileNotFoundError('gz missing')))
    with pytest.raises(OSError, match='gazebo_pose_probe_start_failed:') as caught:
        evidence.capture_poses('test_world', .25)
    assert '"stage": "start"' in str(caught.value)
    assert 'gz missing' in str(caught.value)


def test_sigsegv_retries_once_with_fresh_data_and_visible_diagnostics(monkeypatch, caplog):
    run = Mock(side_effect=[subprocess.CompletedProcess([], -11, '{"pose":[{"id":1}]}', ''),
                            subprocess.CompletedProcess([], 0, '{"pose":[{"id":2}]}', '')])
    monkeypatch.setattr(evidence.subprocess, 'run', run)
    monkeypatch.setattr(evidence.time, 'monotonic', Mock(side_effect=[0, 0, .2, .2, .2]))
    assert evidence.capture_poses('test_world', .25) == [{'pose': [{'id': 2}]}]
    assert run.call_count == 2
    assert 'gazebo_pose_probe_retry:' in caplog.text
    assert '"signal": "SIGSEGV"' in caplog.text
    assert 'gazebo_pose_probe_recovered:' in caplog.text
    assert run.call_args_list[0].kwargs['timeout'] == 5.25
    assert run.call_args_list[1].kwargs['timeout'] == pytest.approx(5.05)


def test_crash_near_deadline_does_not_extend_original_budget(monkeypatch):
    run = result(monkeypatch, -11)
    monkeypatch.setattr(evidence.time, 'monotonic', Mock(side_effect=[0, 0, 5.1, 5.1]))
    with pytest.raises(ValueError, match='gazebo_pose_probe_failed:'):
        evidence.capture_poses('test_world', .25)
    run.assert_called_once()


def test_crash_followed_by_timeout_retains_both_failures(monkeypatch):
    run = Mock(side_effect=[subprocess.CompletedProcess([], -11, '', ''),
                            subprocess.TimeoutExpired(['gz'], 1, output=b'{')])
    monkeypatch.setattr(evidence.subprocess, 'run', run)
    with pytest.raises(TimeoutError) as caught:
        evidence.capture_poses('test_world', .25)
    diagnostic = json.loads(str(caught.value).split(':', 1)[1])
    assert diagnostic['attempt'] == 2
    assert diagnostic['stage'] == 'timeout'
    assert diagnostic['previous_failures'][0]['signal'] == 'SIGSEGV'
    assert run.call_count == 2


@pytest.mark.parametrize('model_id,origin', [(2, 'original'), (1, 'reset')])
def test_recovered_probe_cannot_hide_model_replacement_or_origin_reset(monkeypatch, model_id, origin):
    from simulation.px4_gazebo import patrol

    controller = patrol.MavlinkPatrolController.__new__(patrol.MavlinkPatrolController)
    controller._calibration_error = None
    controller.calibration = {'context': {'model_id': 1, 'origin': 'original'}}
    controller.vehicle = {'gazebo_model_name': 'x500_0'}
    controller._origin_stop = Mock()
    controller._origin_stop.wait.return_value = False
    monkeypatch.setattr(patrol.harness, 'read_state', lambda: {'world_name': 'test_world'})
    monkeypatch.setattr(patrol, 'read_origin_context', lambda vehicle: {'origin': origin})
    run = Mock(side_effect=[subprocess.CompletedProcess([], -11, '', ''),
                            subprocess.CompletedProcess([], 0, json.dumps(
                                {'pose': [{'name': 'x500_0', 'id': model_id}]}), '')])
    monkeypatch.setattr(evidence.subprocess, 'run', run)
    controller._monitor_origin()
    assert controller._calibration_error == 'calibration_origin_process_or_model_changed'
    assert controller._setpoint_error.startswith('calibration_invalid:')
    assert run.call_count == 2
