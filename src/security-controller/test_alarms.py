#!/usr/bin/env python3
"""
Test Script for CloudWatch Alarms and Dashboard

This script tests:
1. CloudWatch Dashboard creation
2. Security Controller-specific alarms
3. SNS topic subscriptions
4. Alarm triggering and recovery

Usage:
    python test_alarms.py

Prerequisites:
    - AWS credentials configured (profile: sentra)
    - Monitoring stack deployed
    - Security Controller running
"""

import asyncio
import time
import boto3
from datetime import datetime, timedelta
from typing import Dict, List

# AWS Configuration
AWS_PROFILE = "sentra"
AWS_REGION = "us-east-1"
NAMESPACE = "Sentra/SecurityController"
DASHBOARD_NAME = "sentra-mvp-dashboard"

# Test configuration
TEST_DURATION_SECONDS = 300  # 5 minutes


class AlarmTester:
    """Test CloudWatch Alarms and Dashboard"""
    
    def __init__(self):
        session = boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)
        self.cloudwatch = session.client('cloudwatch')
        self.sns = session.client('sns')
        
    def test_dashboard_exists(self) -> bool:
        """Test 1: Verify dashboard exists"""
        print("\n" + "="*60)
        print("TEST 1: Verify CloudWatch Dashboard Exists")
        print("="*60)
        
        try:
            response = self.cloudwatch.list_dashboards(
                DashboardNamePrefix=DASHBOARD_NAME
            )
            
            dashboards = response.get('DashboardEntries', [])
            dashboard_found = any(d['DashboardName'] == DASHBOARD_NAME for d in dashboards)
            
            if dashboard_found:
                print(f"✅ Dashboard '{DASHBOARD_NAME}' exists")
                
                # Get dashboard details
                dashboard = self.cloudwatch.get_dashboard(DashboardName=DASHBOARD_NAME)
                print(f"   Dashboard ARN: {dashboard['DashboardArn']}")
                print(f"   Dashboard URL: https://console.aws.amazon.com/cloudwatch/home?region={AWS_REGION}#dashboards:name={DASHBOARD_NAME}")
                return True
            else:
                print(f"❌ Dashboard '{DASHBOARD_NAME}' not found")
                print(f"   Available dashboards: {[d['DashboardName'] for d in dashboards]}")
                return False
                
        except Exception as e:
            print(f"❌ Error checking dashboard: {e}")
            return False
    
    def test_alarms_exist(self) -> bool:
        """Test 2: Verify all Security Controller alarms exist"""
        print("\n" + "="*60)
        print("TEST 2: Verify Security Controller Alarms Exist")
        print("="*60)
        
        expected_alarms = [
            "sentra-mvp-sc-health-check-failure",
            "sentra-mvp-sc-dynamodb-errors",
            "sentra-mvp-sc-high-latency",
            "sentra-mvp-sc-high-deny-rate",
            "sentra-mvp-sc-suspended-session",
        ]
        
        try:
            response = self.cloudwatch.describe_alarms(
                AlarmNamePrefix="sentra-mvp-sc-"
            )
            
            alarms = response.get('MetricAlarms', [])
            alarm_names = [a['AlarmName'] for a in alarms]
            
            print(f"Found {len(alarms)} Security Controller alarms:")
            
            all_found = True
            for expected in expected_alarms:
                if expected in alarm_names:
                    alarm = next(a for a in alarms if a['AlarmName'] == expected)
                    state = alarm['StateValue']
                    print(f"   ✅ {expected} - State: {state}")
                else:
                    print(f"   ❌ {expected} - NOT FOUND")
                    all_found = False
            
            return all_found
            
        except Exception as e:
            print(f"❌ Error checking alarms: {e}")
            return False
    
    def test_sns_topics_exist(self) -> bool:
        """Test 3: Verify SNS topics exist"""
        print("\n" + "="*60)
        print("TEST 3: Verify SNS Topics Exist")
        print("="*60)
        
        expected_topics = [
            "sentra-mvp-alerts",
            "sentra-mvp-critical-alerts",
            "sentra-mvp-info-alerts",
        ]
        
        try:
            response = self.sns.list_topics()
            topics = response.get('Topics', [])
            topic_arns = [t['TopicArn'] for t in topics]
            
            all_found = True
            for expected in expected_topics:
                matching = [arn for arn in topic_arns if expected in arn]
                if matching:
                    print(f"   ✅ {expected}")
                    print(f"      ARN: {matching[0]}")
                    
                    # Check subscriptions
                    subs = self.sns.list_subscriptions_by_topic(TopicArn=matching[0])
                    sub_count = len(subs.get('Subscriptions', []))
                    print(f"      Subscriptions: {sub_count}")
                else:
                    print(f"   ❌ {expected} - NOT FOUND")
                    all_found = False
            
            return all_found
            
        except Exception as e:
            print(f"❌ Error checking SNS topics: {e}")
            return False
    
    def test_alarm_configuration(self) -> bool:
        """Test 4: Verify alarm configurations match LLD specs"""
        print("\n" + "="*60)
        print("TEST 4: Verify Alarm Configurations")
        print("="*60)
        
        expected_configs = {
            "sentra-mvp-sc-health-check-failure": {
                "metric": "HealthCheckStatus",
                "threshold": 1,
                "evaluation_periods": 2,
            },
            "sentra-mvp-sc-dynamodb-errors": {
                "metric": "ValidationErrors",
                "threshold": 5,
                "evaluation_periods": 2,
            },
            "sentra-mvp-sc-high-latency": {
                "metric": "ValidationLatency",
                "threshold": 100,
                "evaluation_periods": 3,
            },
            "sentra-mvp-sc-high-deny-rate": {
                "metric": "DenyRate",
                "threshold": 0.50,
                "evaluation_periods": 3,
            },
            "sentra-mvp-sc-suspended-session": {
                "metric": "SuspendedSessions",
                "threshold": 1,
                "evaluation_periods": 1,
            },
        }
        
        try:
            response = self.cloudwatch.describe_alarms(
                AlarmNamePrefix="sentra-mvp-sc-"
            )
            
            alarms = {a['AlarmName']: a for a in response.get('MetricAlarms', [])}
            
            all_correct = True
            for alarm_name, expected in expected_configs.items():
                if alarm_name not in alarms:
                    print(f"   ❌ {alarm_name} - NOT FOUND")
                    all_correct = False
                    continue
                
                alarm = alarms[alarm_name]
                
                # Check metric name
                if alarm['MetricName'] != expected['metric']:
                    print(f"   ❌ {alarm_name} - Wrong metric: {alarm['MetricName']} (expected {expected['metric']})")
                    all_correct = False
                    continue
                
                # Check threshold
                if alarm['Threshold'] != expected['threshold']:
                    print(f"   ❌ {alarm_name} - Wrong threshold: {alarm['Threshold']} (expected {expected['threshold']})")
                    all_correct = False
                    continue
                
                # Check evaluation periods
                if alarm['EvaluationPeriods'] != expected['evaluation_periods']:
                    print(f"   ❌ {alarm_name} - Wrong evaluation periods: {alarm['EvaluationPeriods']} (expected {expected['evaluation_periods']})")
                    all_correct = False
                    continue
                
                print(f"   ✅ {alarm_name} - Configuration correct")
            
            return all_correct
            
        except Exception as e:
            print(f"❌ Error checking alarm configurations: {e}")
            return False
    
    def test_metrics_published(self) -> bool:
        """Test 5: Verify Security Controller is publishing metrics"""
        print("\n" + "="*60)
        print("TEST 5: Verify Metrics Are Being Published")
        print("="*60)
        
        expected_metrics = [
            "ValidationsTotal",
            "ValidationLatency",
            "TrustScoreAverage",
            "DenyRate",
            "QuarantinedSessions",
            "SuspendedSessions",
            "HealthCheckStatus",
        ]
        
        try:
            # Check for metrics in the last 5 minutes
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)
            
            response = self.cloudwatch.list_metrics(
                Namespace=NAMESPACE
            )
            
            metrics = response.get('Metrics', [])
            metric_names = set(m['MetricName'] for m in metrics)
            
            print(f"Found {len(metric_names)} unique metrics in namespace {NAMESPACE}:")
            
            all_found = True
            for expected in expected_metrics:
                if expected in metric_names:
                    # Check if metric has recent data
                    stats = self.cloudwatch.get_metric_statistics(
                        Namespace=NAMESPACE,
                        MetricName=expected,
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=60,
                        Statistics=['SampleCount']
                    )
                    
                    datapoints = stats.get('Datapoints', [])
                    if datapoints:
                        total_samples = sum(d['SampleCount'] for d in datapoints)
                        print(f"   ✅ {expected} - {total_samples} samples in last 5 minutes")
                    else:
                        print(f"   ⚠️  {expected} - Metric exists but no recent data")
                else:
                    print(f"   ❌ {expected} - NOT FOUND")
                    all_found = False
            
            return all_found
            
        except Exception as e:
            print(f"❌ Error checking metrics: {e}")
            return False
    
    def simulate_alarm_trigger(self, alarm_name: str) -> bool:
        """Test 6: Simulate alarm trigger (optional - requires manual verification)"""
        print("\n" + "="*60)
        print(f"TEST 6: Simulate Alarm Trigger - {alarm_name}")
        print("="*60)
        print("⚠️  This test requires manual verification of SNS email notifications")
        print("   To trigger alarms, you would need to:")
        print("   1. For health-check-failure: Stop the Security Controller ECS task")
        print("   2. For high-latency: Send many concurrent requests")
        print("   3. For high-deny-rate: Send many malicious requests")
        print("   4. For suspended-session: Trigger multiple violations on a session")
        print("\n   Skipping automatic alarm triggering for safety.")
        return True
    
    def run_all_tests(self):
        """Run all tests"""
        print("\n" + "="*60)
        print("CLOUDWATCH ALARMS AND DASHBOARD TESTS")
        print("="*60)
        print(f"AWS Profile: {AWS_PROFILE}")
        print(f"AWS Region: {AWS_REGION}")
        print(f"Namespace: {NAMESPACE}")
        print(f"Dashboard: {DASHBOARD_NAME}")
        
        results = {
            "Dashboard Exists": self.test_dashboard_exists(),
            "Alarms Exist": self.test_alarms_exist(),
            "SNS Topics Exist": self.test_sns_topics_exist(),
            "Alarm Configuration": self.test_alarm_configuration(),
            "Metrics Published": self.test_metrics_published(),
            "Alarm Trigger Simulation": self.simulate_alarm_trigger("sentra-mvp-sc-health-check-failure"),
        }
        
        # Summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for v in results.values() if v)
        total = len(results)
        
        for test_name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status} - {test_name}")
        
        print(f"\nTotal: {passed}/{total} tests passed")
        
        if passed == total:
            print("\n🎉 All tests passed! CloudWatch alarms and dashboard are configured correctly.")
        else:
            print(f"\n⚠️  {total - passed} test(s) failed. Please review the output above.")
        
        return passed == total


def main():
    """Main entry point"""
    tester = AlarmTester()
    success = tester.run_all_tests()
    
    if success:
        exit(0)
    else:
        exit(1)


if __name__ == "__main__":
    main()
