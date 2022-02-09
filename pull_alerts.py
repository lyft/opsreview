from __future__ import absolute_import
from __future__ import division, print_function, unicode_literals

import argparse
import logging
import urllib
from collections import Counter, OrderedDict, defaultdict, namedtuple
from datetime import datetime, timedelta
from dateutil import tz
import dateutil.parser

import pygerduty.v2
from prettytable import PrettyTable

try:
    import settings
except ImportError:
    print("*** Error: Follow setup instructions in README.md to create settings.py")
    raise SystemExit(1)


logger = logging.getLogger(__name__)

pagerduty_service = pygerduty.v2.PagerDuty(settings.PAGERDUTY_API_TOKEN)
LOCAL_TZ = tz.tzlocal()
Tag = namedtuple("Tag", ["tag", "display_name"])
TAGS = [
    Tag(tag="#a", display_name="Actionable (#a)"),
    Tag(tag="#na", display_name="Non Actionable (#na)"),
    Tag(tag="#t", display_name="Transient (#t)"),
    Tag(tag="#s", display_name="Seasonal (#s)"),
    Tag(tag="#abot", display_name="Actionable By Other Team (#abot)"),
]


class FormattedIncident(object):
    def pretty_output(self):
        return u'Time: {}\nService: {}\nDescription: {}\nURL: {}\nNotes:\n{}\n'.format(
            self.created_on.strftime('%A, %B %-d - %-I:%M %p'),
            self.service,
            self.description,
            self.url,
            self.notes,
        )


def recent_incidents_for_services(services, time_window):
    service_ids = [service.id for service in services]
    try:
        recent_incidents = list(pagerduty_service.incidents.list(
            service_ids=service_ids,
            since=datetime.now() - time_window
        ))
        return recent_incidents

    except urllib.error.HTTPError as e:
        if e.reason == 'URI Too Long':
            mid_point = int(len(service_ids)/2)
            return recent_incidents_for_services(
               service_ids=service_ids[:mid_point],
               time_window=time_window
            ) + recent_incidents_for_services(
               service_ids=service_ids[mid_point:],
               time_window=time_window
            )
            return recent_incidents
        raise


def print_all_incidents(
    silent,
    time_window_days,
    group_by_description=False,
    group_by_service=False,
    include_stats=False,
    include_incidents_as_blockquote=False,
):
    services = []
    for escalation_policy in settings.ESCALATION_POLICIES:
        services.extend(list(pagerduty_service.escalation_policies.show(escalation_policy).services))

    recent_incidents = recent_incidents_for_services(services, timedelta(days=time_window_days))
    formatted_incidents = get_formatted_incidents(recent_incidents)

    all_incidents, sorted_description_to_incident_list, sorted_service_to_incident_list = sort_incidents(
        formatted_incidents,
        group_by_description,
        group_by_service
    )
    print_stats(all_incidents, include_stats)
    if include_incidents_as_blockquote:
        print("""# Raw incident log
```
""")
    if group_by_service:
        sorted_group_to_incident_list = sorted_service_to_incident_list
    elif group_by_description:
        sorted_group_to_incident_list = sorted_description_to_incident_list
    if group_by_service or group_by_description:
        for group, incident_list in sorted_group_to_incident_list.iteritems():
            print("########### {}: {} ##########\n".format(len(incident_list), group))
            if not silent:
                for incident in incident_list:
                    print(incident.pretty_output())
    else:
        for incident in all_incidents:
            print(incident.pretty_output())

    print('Total Pages: {}'.format(len(all_incidents)))
    if include_incidents_as_blockquote:
        print("```")


def get_formatted_incidents(recent_incidents):
    formatted_incidents = []
    for incident in recent_incidents:
        formatted_incident = FormattedIncident()
        formatted_incident.service = incident.service.summary
        formatted_incident.url = incident.html_url
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
        formatted_incidents.append(formatted_incident)

    return formatted_incidents


def _tag_incident(incident, tag_stats):
    tagged = False
    for tag in TAGS:
        found_tag = any(tag.tag in note for note in incident.notes)
        if not found_tag:
            continue
        tagged = True
        tag_stats[tag] += 1
    return tagged


def print_stats(all_incidents, include_stats):
    if not include_stats:
        return

    stats_table = PrettyTable()
    stats_table.field_names = ["Incidents", "Number"]
    stats_table.align["Incidents"] = "l"
    stats_table.align["Number"] = "r"

    tag_stats = Counter()

    not_tagged = 0
    for i in all_incidents:
        tagged = _tag_incident(i, tag_stats)
        not_tagged += not tagged

    for tag in TAGS:
        stats_table.add_row([tag.display_name, tag_stats[tag]])
    stats_table.add_row(["Not Tagged", not_tagged])
    stats_table.add_row(["Total", len(all_incidents)])

    print(stats_table)


def sort_incidents(all_incidents, group_by_description, group_by_service):
    description_to_incident_list = defaultdict(list)
    service_to_incident_list = defaultdict(list)
    for incident in all_incidents:
        description_to_incident_list[incident.description].append(incident)
    for incident in all_incidents:
        service_to_incident_list[incident.service].append(incident)
    # Sort by desc count
    sorted_description_to_incident_list = OrderedDict(sorted(
        description_to_incident_list.items(),
        key=lambda x: len(x[1]),
        reverse=True
    ))
    sorted_service_to_incident_list = OrderedDict(sorted(
        service_to_incident_list.items(),
        key=lambda x: len(x[1]),
        reverse=True
    ))

    if group_by_description:
        all_incidents = []
        for incident_list in sorted_description_to_incident_list.itervalues():
            all_incidents += incident_list
    else:
        all_incidents = sorted(all_incidents, key=lambda i: i.created_on)
    return all_incidents, sorted_description_to_incident_list, sorted_service_to_incident_list


if __name__ == '__main__':
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument("--silent",
                        action="store_true",
                        default=False,
                        help="Do not print each description")
    parser.add_argument("--group-by-description",
                        action="store_true",
                        default=False,
                        help="Group PD incidents by description")
    parser.add_argument("--group-by-service",
                        action="store_true",
                        default=False,
                        help="Group PD incidents by service")
    parser.add_argument("--include-stats",
                        action="store_true",
                        default=False,
                        help="Include incidents stats")
    parser.add_argument("--include-incidents-as-blockquote",
                        action="store_true",
                        default=False,
                        help="Include raw incident log as markdown blockquote")
    parser.add_argument('--days',
                        type=int,
                        default=7,
                        help='time window days')
    args = parser.parse_args()
    print_all_incidents(
        silent=args.silent,
        group_by_description=args.group_by_description,
        group_by_service=args.group_by_service,
        include_stats=args.include_stats,
        include_incidents_as_blockquote=args.include_incidents_as_blockquote,
        time_window_days=args.days
    )
