from __future__ import absolute_import
from __future__ import division, print_function, unicode_literals

import argparse
import logging
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from dateutil import tz
import dateutil.parser

import pygerduty.v2

try:
    import settings
except ImportError:
    print("*** Error: Follow setup instructions in README.md to create settings.py")
    raise SystemExit(1)


logger = logging.getLogger(__name__)

pagerduty_service = pygerduty.v2.PagerDuty(settings.PAGERDUTY_API_TOKEN)
LOCAL_TZ = tz.tzlocal()


class FormattedIncident(object):
    def _pretty_output(self):
        return u'Time: {}\nService: {}\nDescription: {}\nURL: {}\nNotes:\n{}\n'.format(
            self.created_on.strftime('%A, %B %-d - %-I:%M %p'),
            self.service,
            self.description,
            self.url,
            self.notes,
        )

    def _csv_output(self):
        return u'{},{},{},{},"{}"'.format(
            self.created_on.strftime('%A, %B %-d - %-I:%M %p'),
            self.service,
            self.description,
            self.url,
            self.notes,
        )

    def output(self, print_csv):
        if print_csv:
            return self._csv_output()
        else:
            return self._pretty_output()

def recent_incidents_for_services(services, time_window):
    service_ids = [service.id for service in services]
    recent_incidents = list(pagerduty_service.incidents.list(
        service_ids=service_ids,
        since=datetime.now() - time_window
    ))
    return recent_incidents


def print_all_incidents(
    silent,
    time_window_days,
    group_by_description=False,
    group_by_service=False,
    print_csv=False,
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
            if not print_csv:
                print("########### {}: {} ##########\n".format(len(incident_list), group))
            if not silent:
                for incident in incident_list:
                    print(incident.output(print_csv))
    else:
        for incident in all_incidents:
            print(incident.output(print_csv))

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


def print_stats(all_incidents, include_stats):
    if not include_stats:
        return
    actionable = 0
    non_actionable = 0
    not_tagged = 0
    for i in all_incidents:
        if is_actionable(i):
            actionable += 1
        elif is_non_actionable(i):
            non_actionable += 1
        else:
            not_tagged += 1
    print("""# Statistics
| Incidents            | Number |
| -------------------- | ------ |
| Total                | {:6} |
| Actionable (#a)      | {:6} |
| Non Actionable (#na) | {:6} |
| Not Tagged           | {:6} |
""".format(len(all_incidents), actionable, non_actionable, not_tagged))


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


def is_actionable(incident):
    return any('#a' in note for note in incident.notes)


def is_non_actionable(incident):
    return any('#na' in note for note in incident.notes)


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
    parser.add_argument("--print-csv",
                        action="store_true",
                        default=False,
                        help="Print in CSV format")
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
        print_csv=args.print_csv,
        include_stats=args.include_stats,
        include_incidents_as_blockquote=args.include_incidents_as_blockquote,
        time_window_days=args.days
    )