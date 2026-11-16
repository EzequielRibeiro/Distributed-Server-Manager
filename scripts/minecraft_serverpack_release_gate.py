#!/usr/bin/env python3
"""One fail-fast, disposable Server Pack regression gate for PR #1013.

`quick` is for incremental changes; `full` extends it with swap, recovery and
Controller/Agent regressions. Neither mode authorizes a release, starts a game,
or modifies the running DSM. GitHub's separate CI remains authoritative.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from xml.etree import ElementTree

ROOT=Path(__file__).resolve().parents[1]

# Run a representative cross-layer chain rather than re-running every workflow
# after each small change. CI still runs its normal complete suite separately.
QUICK=(
    'tests/minecraft_serverpack_migration_provisioning_gate_test.py',
    'tests/minecraft_serverpack_physical_manifest_test.py',
    'tests/minecraft_serverpack_pending_commit_test.py',
    'tests/minecraft_serverpack_pending_publication_atomic_test.py',
    'tests/minecraft_serverpack_live_readiness_test.py',
    'tests/minecraft_serverpack_health_promotion_gate_test.py',
)
EXTENDED=(
    'tests/minecraft_serverpack_physical_swap_e2e_test.py',
    'tests/minecraft_serverpack_migration_swap_test.py',
    'tests/minecraft_serverpack_finalization_real_swap_e2e_test.py',
    'tests/minecraft_serverpack_finalization_subprocess_e2e_test.py',
    'tests/minecraft_serverpack_remote_heartbeat_sqlite_test.py',
    'tests/minecraft_serverpack_remote_heartbeat_cycle_test.py',
    'tests/minecraft_serverpack_remote_producer_test.py',
    'tests/minecraft_serverpack_boot_witness_test.py',
    'tests/minecraft_serverpack_observation_events_test.py',
    'tests/minecraft_serverpack_migration_readiness_test.py',
    'tests/minecraft_serverpack_migration_transaction_test.py',
    'tests/minecraft_serverpack_http_agent_transaction_joined_test.py',
    'tests/minecraft_serverpack_outbox_loopback_http_e2e_test.py',
    'tests/minecraft_serverpack_authenticated_493_http_e2e_test.py',
    'tests/minecraft_serverpack_customer_single_action_e2e_test.py',
    'tests/minecraft_serverpack_customer_session_readmodel_e2e_test.py',
    'tests/minecraft_serverpack_customer_official_preview_session_test.py',
    'tests/minecraft_serverpack_customer_official_http_upload_test.py',
    'tests/minecraft_serverpack_two_transient_systemd_e2e_test.py',
    'tests/minecraft_serverpack_content_convergence_test.py',
    'tests/m9_modpack_bundle_read_model_test.py',
    'tests/universal_content_dashboard_test.py',
)
JS=(
    ('node','--check','dashboard/web/customer-instance-v2.js'),
    ('node','tests/minecraft_serverpack_manifest_drift_ui.test.js'),
    ('node','tests/minecraft_serverpack_migration_enqueue_ui.test.js'),
)


def commands(mode:str)->list[list[str]]:
    if mode not in {'quick','full'}:
        raise ValueError('mode must be quick or full')
    paths=QUICK+(EXTENDED if mode=='full' else ())
    commands_to_run=[list(command) for command in JS]
    if mode=='full':
        # The packaged Agent must boot through legacy updaters too; source
        # checkout imports alone cannot detect missing runtime dependencies.
        commands_to_run.append(['bash','tests/agent_package_test.sh'])
    return commands_to_run+[
        [sys.executable,'-m','pytest','-q','-p','no:cacheprovider',*paths],
    ]


def _junit_coverage(report_file: Path) -> dict:
    """Require structured pytest evidence, including intentional skips.

    XML is produced by pytest's built-in JUnit plugin in disposable storage;
    no private world, server log or game files are copied into the report.
    """
    try:
        document=ElementTree.parse(report_file).getroot()
        if document.tag not in {'testsuite','testsuites'}:
            raise ValueError('unexpected JUnit XML root')
        cases=list(document.iter('testcase'))
        if not cases:
            raise ValueError('no executed pytest cases in JUnit report')
        skips=[]
        failures=0
        for item in cases:
            failure=item.find('failure')
            error=item.find('error')
            if failure is not None or error is not None:
                failures+=1
            skip=item.find('skipped')
            if skip is not None:
                skips.append({
                    'test':(str(item.get('classname') or '')+'.'+str(item.get('name') or ''))[:220],
                    'reason':str(skip.get('message') or 'skipped without reason')[:180],
                })
        return {
            'status':'partial' if skips else 'complete',
            'collected':len(cases),
            'passed':len(cases)-failures-len(skips),
            'skipped':len(skips),
            'failed':failures,
            'skipped_cases':skips,
        }
    except (OSError, ValueError, ElementTree.ParseError) as exc:
        return {
            'status':'unavailable',
            'reason':type(exc).__name__,
            'collected':None,
            'passed':None,
            'skipped':None,
            'failed':None,
            'skipped_cases':[],
        }


def run(mode:str)->dict:
    env=os.environ.copy()
    env['PYTHONPATH']=str(ROOT)+os.pathsep+env.get('PYTHONPATH','')
    env['PYTHONDONTWRITEBYTECODE']='1'
    results=[]
    coverage={'status':'not_run','skipped_cases':[]}
    with tempfile.TemporaryDirectory(prefix='dsm1013-gate-') as scratch:
        junit=Path(scratch)/'pytest.xml'
        for command in commands(mode):
            step=list(command)
            is_pytest=(len(step)>=3 and step[1:3]==['-m','pytest'])
            if is_pytest:
                step.append('--junitxml='+str(junit))
            print('$ '+' '.join(step),flush=True)
            started=time.monotonic()
            try:
                result=subprocess.run(step,cwd=ROOT,env=env,check=False)
                code=result.returncode
            except OSError as exc:
                print(f'Command could not start: {exc}',file=sys.stderr,flush=True)
                code=127
            if is_pytest and code==0:
                coverage=_junit_coverage(junit)
                if coverage['status']=='unavailable' or coverage.get('failed'):
                    # A green exit code without a usable test inventory must
                    # never be reported as complete evidence for this gate.
                    code=1
            results.append({'command':step,'exit_code':code,
                            'elapsed_seconds':round(time.monotonic()-started,2)})
            if code!=0:
                break  # Never advance to another phase after failure.
    passed=(len(results)==len(commands(mode))
            and all(x['exit_code']==0 for x in results))
    return {
        'kind':'MinecraftServerPackRegressionGate',
        'mode':mode,
        'status':'tests_passed' if passed else 'tests_failed',
        'coverage':coverage,
        # This measures only the tests SELECTED by quick/full, not all
        # environment-gated E2E cases or a real private-world restore boot.
        'selected_suite_coverage_complete':passed and coverage['status']=='complete',
        # A clean quick/full pytest run never establishes environment acceptance.
        # The real restored-world boot + 14-day backup capacity are not part of
        # this script and must be attested in a separately authorized workflow.
        'environment_test_coverage_complete':False,
        'restored_private_world_boot_verified':False,
        'backup_14_day_capacity_verified':False,
        'acceptance_status':'blocked',
        'acceptance_blockers':(
            (['full_suite_not_executed'] if mode=='quick' else [])+
            (['selected_suite_skipped_tests'] if coverage['status']=='partial' else [])+
            ['restored_private_world_boot_not_verified',
             'backup_14_day_capacity_not_verified']
        ),
        'release_authorized':False,
        'steps':results,
    }


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('quick','full'),default='quick')
    args=parser.parse_args()
    report=run(args.mode)
    print(json.dumps(report,sort_keys=True),flush=True)
    return 0 if report['status']=='tests_passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
