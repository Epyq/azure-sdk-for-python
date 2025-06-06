# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See LICENSE.txt in the project root for
# license information.
# -------------------------------------------------------------------------
from datetime import timedelta

from azure.monitor.query import MetricsClient, MetricAggregationType
from azure.monitor.query._version import VERSION

from base_testcase import MetricsClientTestCase


METRIC_NAME = "requests/count"
METRIC_RESOURCE_PROVIDER = "Microsoft.Insights/components"


class TestMetricsClient(MetricsClientTestCase):

    def test_batch_metrics_auth(self, recorded_test, monitor_info):
        client: MetricsClient = self.get_client(MetricsClient, self.get_credential(MetricsClient))
        responses = client.query_resources(
            resource_ids=[monitor_info["metrics_resource_id"]],
            metric_namespace=METRIC_RESOURCE_PROVIDER,
            metric_names=[METRIC_NAME],
            aggregations=[MetricAggregationType.COUNT],
        )
        assert responses
        assert len(responses) == 1

    def test_batch_metrics_granularity(self, recorded_test, monitor_info):
        client: MetricsClient = self.get_client(MetricsClient, self.get_credential(MetricsClient))
        responses = client.query_resources(
            resource_ids=[monitor_info["metrics_resource_id"]],
            metric_namespace=METRIC_RESOURCE_PROVIDER,
            metric_names=[METRIC_NAME],
            granularity=timedelta(minutes=5),
            aggregations=[MetricAggregationType.COUNT],
        )
        assert responses
        for response in responses:
            assert response.granularity == timedelta(minutes=5)
            response.metrics
            metric = response.metrics[METRIC_NAME]
            assert metric.timeseries
            for t in metric.timeseries:
                assert t.metadata_values is not None

    def test_client_different_endpoint(self):
        credential = self.get_credential(MetricsClient)
        endpoint = "https://usgovvirginia.metrics.monitor.azure.us"
        audience = "https://metrics.monitor.azure.us"
        client = MetricsClient(endpoint, credential, audience=audience)

        assert client._endpoint == endpoint
        assert f"{audience}/.default" in client._client._config.authentication_policy._scopes

    def test_client_user_agent(self):
        client: MetricsClient = self.get_client(MetricsClient, self.get_credential(MetricsClient))
        assert f"monitor-query/{VERSION}" in client._client._config.user_agent_policy.user_agent
