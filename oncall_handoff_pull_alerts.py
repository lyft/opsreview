import argparse
import logging
from collections import OrderedDict
from datetime import datetime
from datetime import timedelta

import dateutil.parser
import pygerduty.v2
import settings
from dateutil import relativedelta
from dateutil import tz


logger = logging.getLogger(__name__)

pagerduty_service = pygerduty.v2.PagerDuty(settings.PAGERDUTY_API_TOKEN)
LOCAL_TZ = tz.tzlocal()


class FormattedIncident:
    def pretty_output(self):
        return 'Time: {}\nService: {}\nDescription: {}\nURL: {}\nNotes:\n{}\n'.format(
            self.created_on.strftime('%A, %B %-d - %-I:%M %p'),
            self.service,
            self.description,
            self.url,
            self.notes,
        )

    @property
    def is_high_urgency(self):
        return not (self.urgency == 'low' or '-low-' in self.service)


def recent_incidents_for_services(services, start_datetime):
    service_ids = [service.id for service in services]
    on_call_start = get_oncall_start(start_datetime)
    on_call_end = on_call_start + timedelta(days=7)
    recent_incidents = list(pagerduty_service.incidents.list(
        service_ids=service_ids,
        since=on_call_start,
        until=on_call_end
    ))
    return recent_incidents


def get_oncall_start(start_datetime):
    # if start datetime is provided, use that
    if start_datetime:
        return datetime.strptime(start_datetime, '%Y-%m-%d %H:%M')
    # oncall starts on Monday 1PM
    # get last Monday but not today if today is a Monday
    today = datetime.now(tz=tz.tzlocal())
    today = today.replace(hour=13, minute=0, second=0, microsecond=0)
    if today.weekday() == 0:
        on_call_start = today + relativedelta.relativedelta(days=-1, weekday=relativedelta.MO(-1))
    else:
        on_call_start = today + relativedelta.relativedelta(weekday=relativedelta.MO(-1))

    return(on_call_start)


def print_all_incidents(
    include_low,
    start_datetime
):
    services = []
    for escalation_policy in settings.ESCALATION_POLICIES:
        services.extend(list(pagerduty_service.escalation_policies.show(escalation_policy).services))

    recent_incidents = recent_incidents_for_services(services, start_datetime)
    recent_incidents.sort(key=lambda x: x.created_at)
    all_incidents = get_formatted_incidents(recent_incidents)

    print_pages_by_notes(all_incidents)

    high_urg_incidents = [i for i in all_incidents if i.is_high_urgency]
    low_urg_incidents = [i for i in all_incidents if not i.is_high_urgency]
    print_stats(high_urg_incidents, low_urg_incidents)

    print(f'Total Pages: {len(all_incidents)}')


def print_pages_by_notes(incidents):
    note_to_incident_list = OrderedDict()
    for incident in incidents:
        if incident.last_note not in note_to_incident_list:
            note_to_incident_list[incident.last_note] = []
        note_to_incident_list[incident.last_note].append(incident)

    for note, incidents in note_to_incident_list.items():
        print(f'\n{note} generated {len(incidents)} incidents:')
        for i in incidents:
            print(f'\t- [{i.created_on}] {i.description} ({i.url})')


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
            logger.warning(f'action=get_description status=not_found incident={incident}')
        formatted_incident.created_on = dateutil.parser.parse(incident.created_at).astimezone(LOCAL_TZ)

        notes = list(incident.notes.list())
        formatted_notes = []
        for note in notes:
            formatted_notes.append(f'{note.user.summary}: {note.content}')
        formatted_incident.notes = formatted_notes
        formatted_incident.last_note = formatted_notes[-1] if formatted_notes else 'NO NOTE'
        formatted_incidents.append(formatted_incident)

    return formatted_incidents


def print_stats(high_urg_incidents, low_urg_incidents):
    h_a, h_na, h_t, h_abot, h_s, h_nt = get_breakdown(high_urg_incidents)
    l_a, l_na, l_t, l_abot, l_s, l_nt = get_breakdown(low_urg_incidents)
    print("""\n# Statistics
| Incidents                        | High Urgency | Low Urgency |
| -------------------------------- | ------------ | ----------- |
| Actionable (#a)                  | {:12} | {:11} |
| Actionable By Other Team (#abot) | {:12} | {:11} |
| Non Actionable (#na)             | {:12} | {:11} |
| Transient (#t)                   | {:12} | {:11} |
| Seasonal (#s)                    | {:12} | {:11} |
| Not Tagged                       | {:12} | {:11} |
| TOTAL                            | {:12} | {:11} |
""".format(h_a, l_a, h_abot, l_abot, h_na, l_na, h_t, l_t, h_s, l_s, h_nt, l_nt,
           len(high_urg_incidents), len(low_urg_incidents)))


def get_breakdown(incidents):
    actionable = 0
    non_actionable = 0
    transient = 0
    actionable_by_other_team = 0
    seasonal = 0
    not_tagged = 0
    for i in incidents:
        if is_actionable_by_other_team(i):
            actionable_by_other_team += 1
        elif is_actionable(i):
            actionable += 1
        elif is_non_actionable(i):
            non_actionable += 1
        elif is_transient(i):
            transient += 1
        elif is_seasonal(i):
            seasonal += 1
        else:
            not_tagged += 1
    return actionable, non_actionable, transient, actionable_by_other_team, seasonal, not_tagged


def is_actionable(incident):
    return any('#a' in note for note in incident.notes)


def is_non_actionable(incident):
    return any('#na' in note for note in incident.notes)


def is_transient(incident):
    return any('#t' in note for note in incident.notes)


def is_actionable_by_other_team(incident):
    return any('#abot' in note for note in incident.notes)


def is_seasonal(incident):
    return any('#s' in note for note in incident.notes)


if __name__ == '__main__':
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-low",
                        action="store_true",
                        default=False,
                        help="Include low urgency detailed view")
    parser.add_argument('--start-datetime',
                        type=str,
                        help='The specific start datetime of a period of incidents in YYYY-MM-DD HH:MM format')
    args = parser.parse_args()
    print_all_incidents(
        include_low=args.include_low,
        start_datetime=args.start_datetime
    )