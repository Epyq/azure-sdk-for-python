# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

import asyncio
import pytest
import time

try:
    import uamqp
except (ModuleNotFoundError, ImportError):
    uamqp = None

from azure.eventhub import EventData, TransportType
from azure.eventhub.exceptions import EventHubError
from azure.eventhub.aio import EventHubProducerClient, EventHubConsumerClient
from azure.eventhub._pyamqp._message_backcompat import LegacyMessage


@pytest.mark.liveTest
@pytest.mark.asyncio
async def test_receive_end_of_stream_async(auth_credential_senders_async, uamqp_transport, client_args):
    async def on_event(partition_context, event):
        if partition_context.partition_id == "0":
            assert event.body_as_str() == "Receiving only a single event"
            assert list(event.body)[0] == b"Receiving only a single event"
            on_event.called = True
            assert event.partition_key == b"0"
            event_str = str(event)
            assert ", offset: " in event_str
            assert ", sequence_number: " in event_str
            assert ", enqueued_time: " in event_str
            assert ", partition_key: 0" in event_str
        if uamqp_transport:
            assert isinstance(event.message, uamqp.Message)
        else:
            assert isinstance(event.message, LegacyMessage)

    on_event.called = False
    fully_qualified_namespace, eventhub_name, credential, senders = auth_credential_senders_async
    # test async producer client
    producer_client = EventHubProducerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        uamqp_transport=uamqp_transport,
        **client_args,
    )
    partitions = await producer_client.get_partition_ids()
    senders = []
    for p in partitions:
        sender = producer_client._create_producer(partition_id=p)
        senders.append(sender)

    client = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        consumer_group="$default",
        **client_args,
    )
    async with client:
        task = asyncio.ensure_future(client.receive(on_event, partition_id="0", starting_position="@latest"))
        await asyncio.sleep(10)
        assert on_event.called is False
        await senders[0].send(EventData(b"Receiving only a single event"), partition_key="0")
        await asyncio.sleep(10)
        assert on_event.called is True

    await task
    for s in senders:
        await s.close()
    await producer_client.close()


@pytest.mark.parametrize(
    "position, inclusive, expected_result",
    [
        ("offset", False, "Exclusive"),
        ("offset", True, "Inclusive"),
        ("sequence", False, "Exclusive"),
        ("sequence", True, "Inclusive"),
        ("enqueued_time", False, "Exclusive"),
    ],
)
@pytest.mark.liveTest
@pytest.mark.asyncio
async def test_receive_with_event_position_async(
    auth_credential_senders_async, position, inclusive, expected_result, uamqp_transport, client_args
):
    async def on_event(partition_context, event):
        assert partition_context.last_enqueued_event_properties.get("sequence_number") == event.sequence_number
        assert partition_context.last_enqueued_event_properties.get("offset") == event.offset
        assert partition_context.last_enqueued_event_properties.get("enqueued_time") == event.enqueued_time
        assert partition_context.last_enqueued_event_properties.get("retrieval_time") is not None

        if position == "offset":
            on_event.event_position = event.offset
        elif position == "sequence":
            on_event.event_position = event.sequence_number
        else:
            on_event.event_position = event.enqueued_time
        on_event.event = event

    on_event.event_position = None
    fully_qualified_namespace, eventhub_name, credential, senders = auth_credential_senders_async
    senders[0].send(EventData(b"Inclusive"))
    client = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        consumer_group="$default",
        uamqp_transport=uamqp_transport,
        **client_args,
    )
    async with client:
        task = asyncio.ensure_future(
            client.receive(
                on_event,
                starting_position="-1",
                starting_position_inclusive=inclusive,
                track_last_enqueued_event_properties=True,
            )
        )
        await asyncio.sleep(10)
        assert on_event.event_position is not None
    await task
    senders[0].send(EventData(expected_result))
    client2 = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        consumer_group="$default",
        uamqp_transport=uamqp_transport,
        **client_args,
    )
    async with client2:
        task = asyncio.ensure_future(
            client2.receive(
                on_event,
                starting_position=on_event.event_position,
                starting_position_inclusive=inclusive,
                track_last_enqueued_event_properties=True,
            )
        )
        await asyncio.sleep(10)
        assert on_event.event.body_as_str() == expected_result
    await task


@pytest.mark.liveTest
@pytest.mark.asyncio
async def test_receive_owner_level_async(auth_credential_senders_async, uamqp_transport, client_args):
    app_prop = {"raw_prop": "raw_value"}

    async def on_event(partition_context, event):
        pass

    async def on_error(partition_context, error):
        on_error.error = error

    on_error.error = None
    fully_qualified_namespace, eventhub_name, credential, senders = auth_credential_senders_async
    client1 = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        consumer_group="$default",
        uamqp_transport=uamqp_transport,
        **client_args,
    )
    client2 = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        consumer_group="$default",
        uamqp_transport=uamqp_transport,
        **client_args,
    )
    async with client1, client2:
        task1 = asyncio.ensure_future(
            client1.receive(on_event, partition_id="0", starting_position="-1", on_error=on_error)
        )
        for i in range(5):
            ed = EventData("Event Number {}".format(i))
            senders[0].send(ed)
        await asyncio.sleep(10)
        task2 = asyncio.ensure_future(
            client2.receive(on_event, partition_id="0", starting_position="-1", owner_level=1)
        )
        for i in range(5):
            ed = EventData("Event Number {}".format(i))
            senders[0].send(ed)
        await asyncio.sleep(20)
    await task1
    await task2
    assert isinstance(on_error.error, EventHubError)


@pytest.mark.liveTest
@pytest.mark.asyncio
@pytest.mark.no_amqpproxy # Proxy requires TransportType.Amqp
async def test_receive_over_websocket_async(auth_credential_senders_async, uamqp_transport, client_args):
    app_prop = {"raw_prop": "raw_value"}
    content_type = "text/plain"
    message_id_base = "mess_id_sample_"

    async def on_event(partition_context, event):
        on_event.received.append(event)
        on_event.app_prop = event.properties

    on_event.received = []
    on_event.app_prop = None
    fully_qualified_namespace, eventhub_name, credential, senders = auth_credential_senders_async
    client = EventHubConsumerClient(
        fully_qualified_namespace=fully_qualified_namespace,
        eventhub_name=eventhub_name,
        credential=credential(),
        consumer_group="$default",
        transport_type=TransportType.AmqpOverWebsocket,
        uamqp_transport=uamqp_transport,
        **client_args,
    )

    event_list = []
    for i in range(5):
        ed = EventData("Event Number {}".format(i))
        ed.properties = app_prop
        ed.content_type = content_type
        ed.correlation_id = message_id_base
        ed.message_id = message_id_base + str(i)
        event_list.append(ed)
    senders[0].send(event_list)
    single_ed = EventData("Event Number {}".format(6))
    single_ed.properties = app_prop
    single_ed.content_type = content_type
    single_ed.correlation_id = message_id_base
    single_ed.message_id = message_id_base + str(6)
    senders[0].send(single_ed)

    async with client:
        task = asyncio.ensure_future(client.receive(on_event, partition_id="0", starting_position="-1"))
        await asyncio.sleep(10)
    await task
    assert len(on_event.received) == 6
    for ed in on_event.received:
        assert ed.correlation_id == message_id_base
        assert message_id_base in ed.message_id
        assert ed.content_type == "text/plain"
        assert ed.properties[b"raw_prop"] == b"raw_value"
