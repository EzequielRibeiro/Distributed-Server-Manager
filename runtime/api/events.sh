#!/bin/sh
#
# DSM Universal Runtime
# Events API
#

runtime_event_provider()
{
    runtime_get events provider
}


runtime_event_enabled()
{
    runtime_get features events
}


runtime_event_sources()
{
    runtime_driver_call driver_events
}