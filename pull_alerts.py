# Copy this file into pull_alerts.py in from https://github.com/lyft/opsreview
# To include low_urgency call it like this: python pull_alerts.py --include-low

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import argparse
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import dateutil.parser
import pygerduty.v2
from dateutil import relativedelta, tz

import settings

logger = logging.getLogger(__name__)

pagerduty_service = pygerduty.v2.PagerDuty(settings.PAGERDUTY_API_TOKEN)
LOCAL_TZ = tz.tzlocal()


class FormattedIncident(object):
    def pretty_output(self):
        return u'Time: {}\nService: {}\nDescription: {}\nURL: {}\nNotes:\n{}\n'.format(
            self.formatted_created_at,
            self.service,
            self.description,
            self.url,
            self.notes,
        )

    @property
    def is_high_urgency(self):
        return not (self.urgency == 'low' or '-low-' in self.service)

    @property
    def formatted_created_at(self):
        return self.created_on.strftime('%a, %b %-d - %-I:%M %p')


def recent_incidents_for_services(services):
    service_ids = [service.id for service in services]
    on_call_start = get_oncall_start()
    on_call_end = on_call_start + timedelta(days=8)
    recent_incidents = list(pagerduty_service.incidents.list(
        service_ids=service_ids,
        since=on_call_start,
        until=on_call_end
    ))
    return recent_incidents


def get_oncall_start():
    # oncall starts on Wednesday 12PM
    # get last Wed but not today if today is a Wed
    today = datetime.now(tz=tz.tzlocal())
    today = today.replace(hour=12, minute=0, second=0, microsecond=0)
    if today.weekday() == 2:
        on_call_start = today + relativedelta.relativedelta(days=-1, weekday=relativedelta.WE(-1))
    else:
        on_call_start = today + relativedelta.relativedelta(weekday=relativedelta.WE(-1))

    return on_call_start


def print_all_incidents(
    include_low
):
    services = []
    for escalation_policy in settings.ESCALATION_POLICIES:
        services.extend(list(pagerduty_service.escalation_policies.show(escalation_policy).services))

    recent_incidents = recent_incidents_for_services(services)
    all_incidents = get_formatted_incidents(recent_incidents)
    high_urg_incidents = [i for i in all_incidents if i.is_high_urgency]
    low_urg_incidents = [i for i in all_incidents if not i.is_high_urgency]
    print('\n########## High Urgency Pages ##########')
    print_pages_by_description(high_urg_incidents)
    if include_low:
        print('\n########## Low Urgency Pages ##########')
        print_pages_by_description(low_urg_incidents)

    print_stats(high_urg_incidents, low_urg_incidents)

    print('Total Pages: {}'.format(len(all_incidents)))


def print_pages_by_notes(incidents):
    note_to_incident_list = defaultdict(list)
    for incident in incidents:
        note_to_incident_list[incident.last_note].append(incident)

    for note, incidents in note_to_incident_list.items():
        print('\n{} generated {} incidents:'.format(note, len(incidents)))
        for i in incidents:
            print('\t- {} ({})'.format(i.description, i.url))


def print_pages_by_description(incidents):
    desc_to_incident_list = defaultdict(list)
    for incident in incidents:
        desc_to_incident_list[incident.description].append(incident)

    for desc, incidents in desc_to_incident_list.items():
        print('\n**{}** [Paged {} times]:'.format(desc, len(incidents)))
        for i in incidents:
            if i.last_note == 'NO NOTE':
                print('- [alarm paged]({}) - no note'.format(i.url))
            else:
                print('- [alarm paged]({}) - {}'.format(i.url, i.last_note))


def get_formatted_incidents(recent_incidents):
    formatted_incidents = []
    for incident in recent_incidents:
        formatted_incident = FormattedIncident()
        formatted_incident.service = incident.service.summary
        formatted_incident.url = incident.html_url
        formatted_incident.urgency = incident.urgency
        if hasattr(incident, 'title'):
            formatted_incident.description = incident.title
        elif hasattr(incident, 'summary'):
            formatted_incident.description = incident.summary
        elif hasattr(incident, 'id'):
            formatted_incident.description = incident.id
        else:
            logger.warning('action=get_description status=not_found incident={}'.format(incident))
        formatted_incident.created_on = dateutil.parser.parse(incident.created_at).astimezone(LOCAL_TZ)

        notes = list(incident.notes.list())
        formatted_notes = []
        for note in notes:
            formatted_notes.append(u'{}: {}'.format(note.user.summary, note.content))
        formatted_incident.notes = formatted_notes
        formatted_incident.last_note = formatted_notes[-1] if formatted_notes else 'NO NOTE'
        formatted_incidents.append(formatted_incident)

    return formatted_incidents


def print_stats(high_urg_incidents, low_urg_incidents):
    h_a, h_na, h_t, h_nt = get_breakdown(high_urg_incidents)
    l_a, l_na, l_t, l_nt = get_breakdown(low_urg_incidents)
    oncall_start = get_oncall_start()
    oncall_end = oncall_start + timedelta(days=7)
    formatted_start = oncall_start.strftime('%m/%d %H:%M')
    formatted_end = oncall_end.strftime('%m/%d %H:%M')
    print("""\n# Statistics from {} to {}
| Incidents            | High Urgency | Low Urgency |
| -------------------- | ------------ | ----------- |
| Actionable (#a)      | {:12} | {:11} |
| Non Actionable (#na) | {:12} | {:11} |
| Transient (#t)       | {:12} | {:11} |
| Not Tagged           | {:12} | {:11} |
| TOTAL                | {:12} | {:11} |
""".format(
        formatted_start, formatted_end, h_a, l_a, h_na, l_na, h_t, l_t, h_nt, l_nt,
        len(high_urg_incidents), len(low_urg_incidents)
    ))


def get_breakdown(incidents):
    actionable = 0
    non_actionable = 0
    transient = 0
    not_tagged = 0
    for i in incidents:
        if is_actionable(i):
            actionable += 1
        elif is_non_actionable(i):
            non_actionable += 1
        elif is_transient(i):
            transient += 1
        else:
            not_tagged += 1
    return actionable, non_actionable, transient, not_tagged


def is_actionable(incident):
    return any('#a' in note for note in incident.notes)


def is_non_actionable(incident):
    return any('#na' in note for note in incident.notes)


def is_transient(incident):
    return any('#t' in note for note in incident.notes)


if __name__ == '__main__':
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-low",
                        action="store_true",
                        default=False,
                        help="Include low urgency detailed view")
    args = parser.parse_args()
    print_all_incidents(
        include_low=args.include_low
    )
