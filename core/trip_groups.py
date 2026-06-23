import datetime
import re

from django.db import transaction
from django.db.models import Prefetch
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from .models import Invoice, TripGroup, TripGroupInvoice, TripSeparator, User


CITY_PATTERN = re.compile(
    r'(郑州|北京|上海|广州|深圳|杭州|南京|苏州|成都|重庆|天津|武汉|西安|长沙|青岛|厦门|福州|济南|合肥|南昌|昆明|贵阳|太原|石家庄|沈阳|大连|长春|哈尔滨|兰州|银川|乌鲁木齐|呼和浩特|海口|三亚|宁波|无锡|东莞|佛山)'
)


def infer_home_city(user: User, explicit_home_city: str = '') -> str:
    if explicit_home_city:
        return explicit_home_city.strip()

    candidates = [
        user.city or '',
        user.company or '',
        user.department or '',
        user.real_name or '',
        user.username or '',
    ]
    for text in candidates:
        match = CITY_PATTERN.search(text)
        if match:
            return match.group(1)
    return ''


def is_long_distance_transport(invoice: Invoice) -> bool:
    product_name = (invoice.product_name or '').strip()
    if product_name in {'铁路客票', '航空客票'}:
        return True
    keywords = ('铁路', '高铁', '动车', '火车', '机票', '航班', '航空', '客票')
    return any(keyword in product_name for keyword in keywords)


def has_ride_hailing_trip_statement(invoice: Invoice) -> bool:
    prefetched = getattr(invoice, 'prefetched_attachments', None)
    if prefetched is not None:
        return any(attachment.attachment_type == 'RIDE_HAILING_TRIP_STATEMENT' for attachment in prefetched)
    return invoice.attachments.filter(attachment_type='RIDE_HAILING_TRIP_STATEMENT').exists()


def trip_statement_date_range(invoice: Invoice) -> tuple[datetime.date | None, datetime.date | None]:
    prefetched = getattr(invoice, 'prefetched_attachments', None)
    attachments = prefetched if prefetched is not None else invoice.attachments.all()
    statement_dates = [
        (attachment.travel_start_date, attachment.travel_end_date)
        for attachment in attachments
        if attachment.attachment_type == 'RIDE_HAILING_TRIP_STATEMENT'
    ]
    starts = [start for start, _ in statement_dates if start]
    ends = [end or start for start, end in statement_dates if end or start]
    if starts or ends:
        return (min(starts) if starts else min(ends), max(ends) if ends else max(starts))
    return None, None


def trip_statement_info(invoice: Invoice) -> dict | None:
    prefetched = getattr(invoice, 'prefetched_attachments', None)
    attachments = prefetched if prefetched is not None else invoice.attachments.all()
    statements = [
        attachment
        for attachment in attachments
        if attachment.attachment_type == 'RIDE_HAILING_TRIP_STATEMENT'
    ]
    if not statements:
        return None

    starts = [item.travel_start_date for item in statements if item.travel_start_date]
    ends = [item.travel_end_date or item.travel_start_date for item in statements if item.travel_end_date or item.travel_start_date]
    first = statements[0]
    departure_place = next((item.travel_departure_place for item in statements if item.travel_departure_place), '')
    arrival_place = next((item.travel_arrival_place for item in reversed(statements) if item.travel_arrival_place), '')
    return {
        'id': first.pk,
        'name': first.original_name,
        'file': first.file.url if getattr(first, 'file', None) else '',
        'travel_start_date': min(starts).isoformat() if starts else None,
        'travel_end_date': max(ends).isoformat() if ends else None,
        'travel_departure_place': departure_place,
        'travel_arrival_place': arrival_place,
        'travel_details': first.travel_details or [],
        'travel_total_amount': str(first.travel_total_amount) if first.travel_total_amount is not None else None,
        'application_date': first.application_date.isoformat() if first.application_date else None,
        'applicant_phone': first.applicant_phone,
    }


def timeline_sort_date(invoice: Invoice) -> datetime.date | None:
    statement_start, _ = trip_statement_date_range(invoice)
    return statement_start or invoice.invoice_date


def timeline_sort_datetime(invoice: Invoice) -> datetime.datetime:
    statement_start, _ = trip_statement_date_range(invoice)
    if statement_start:
        return datetime.datetime.combine(statement_start, datetime.time.min, tzinfo=datetime.timezone.utc)
    if invoice.service_start_date:
        return invoice.service_start_date
    if invoice.invoice_date:
        return datetime.datetime.combine(invoice.invoice_date, datetime.time.min, tzinfo=datetime.timezone.utc)
    return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def matches_home_city(place: str, home_city: str) -> bool:
    if not place or not home_city:
        return False
    normalized_place = str(place).strip()
    normalized_home = str(home_city).strip()
    return normalized_home in normalized_place or normalized_place in normalized_home


def transport_mode(invoice: Invoice) -> str:
    product_name = invoice.product_name or ''
    if '航' in product_name or '机票' in product_name:
        return 'AIR'
    if any(keyword in product_name for keyword in ('铁路', '高铁', '动车', '火车')):
        return 'RAIL'
    return 'OTHER'


def infer_reimbursement_category(invoice: Invoice) -> str:
    if invoice.invoice_type in {'TRANSPORT', 'ACCOMMODATION', 'OTHER'}:
        return invoice.invoice_type
    return 'OTHER'


def build_default_trip_title(
    home_city: str,
    destination_places: list[str],
    trip_index: int,
    start_date: datetime.date | None = None,
    end_date: datetime.date | None = None,
) -> str:
    if destination_places:
        destination_text = ' / '.join(destination_places)
        if home_city:
            return f'{home_city} - {destination_text}行程'
        return f'{destination_text}行程'

    if start_date and end_date:
        if start_date == end_date:
            return f'{start_date.isoformat()} 行程'
        return f'{start_date.isoformat()} 至 {end_date.isoformat()} 行程'

    return f'第{trip_index}次行程'


def build_trip_signature(invoices: list[Invoice]) -> tuple[int, ...]:
    core_trip_invoices = [invoice for invoice in invoices if is_long_distance_transport(invoice)] or invoices
    return tuple(sorted(invoice.pk for invoice in core_trip_invoices if invoice.pk is not None))


def serialize_trip_invoice(
    invoice: Invoice,
    home_city: str,
    reimbursement_category: str | None = None,
    trip_group_id: int | None = None,
) -> dict:
    statement_start_date, statement_end_date = trip_statement_date_range(invoice)
    statement_info = trip_statement_info(invoice)
    display_date = statement_start_date or invoice.invoice_date
    return {
        'id': invoice.pk,
        'invoice_number': invoice.invoice_number,
        'invoice_date': display_date.isoformat() if display_date else None,
        'service_start_date': (
            invoice.service_start_date.isoformat()
            if invoice.service_start_date and not statement_start_date
            else None
        ),
        'amount': str(invoice.amount) if invoice.amount is not None else None,
        'file': invoice.file.url if getattr(invoice, 'file', None) else '',
        'product_name': invoice.product_name,
        'invoice_type': invoice.invoice_type,
        'reimbursement_category': reimbursement_category or infer_reimbursement_category(invoice),
        'departure_place': statement_info.get('travel_departure_place') if statement_info and statement_info.get('travel_departure_place') else invoice.departure_place,
        'arrival_place': statement_info.get('travel_arrival_place') if statement_info and statement_info.get('travel_arrival_place') else invoice.arrival_place,
        'mode': transport_mode(invoice),
        'travel_start_date': statement_start_date.isoformat() if statement_start_date else None,
        'travel_end_date': statement_end_date.isoformat() if statement_end_date else None,
        'has_trip_statement': has_ride_hailing_trip_statement(invoice),
        'trip_statement': statement_info,
        'is_depart_from_home': matches_home_city(invoice.departure_place or '', home_city),
        'is_arrive_home': matches_home_city(invoice.arrival_place or '', home_city),
        'trip_group_id': trip_group_id,
    }


def build_trip_summary(
    home_city: str,
    invoices: list[Invoice],
    trip_index: int,
    trip_group: TripGroup | None = None,
    trip_links: list[TripGroupInvoice] | None = None,
) -> dict:
    ordered_invoices = sorted(invoices, key=lambda item: (timeline_sort_datetime(item), item.created_at, item.pk or 0))
    link_by_invoice_id = {
        link.invoice.pk: link
        for link in (trip_links or [])
    }
    core_trip_invoices = [invoice for invoice in ordered_invoices if is_long_distance_transport(invoice)] or ordered_invoices

    start_date = timeline_sort_date(core_trip_invoices[0]) if core_trip_invoices else None
    end_date = timeline_sort_date(core_trip_invoices[-1]) if core_trip_invoices else None
    destination_places: list[str] = []
    for invoice in core_trip_invoices:
        for place in (invoice.departure_place, invoice.arrival_place):
            if place and not matches_home_city(place, home_city) and place not in destination_places:
                destination_places.append(place)

    summary = {
        'trip_no': trip_index,
        'start_date': start_date.isoformat() if start_date else None,
        'end_date': end_date.isoformat() if end_date else None,
        'duration_days': ((end_date - start_date).days + 1) if start_date and end_date else None,
        'is_complete': bool(
            core_trip_invoices
            and matches_home_city(core_trip_invoices[0].departure_place or '', home_city)
            and matches_home_city(core_trip_invoices[-1].arrival_place or '', home_city)
        ),
        'destinations': destination_places,
        'transport_modes': sorted({transport_mode(invoice) for invoice in core_trip_invoices}),
        'invoices': [
            serialize_trip_invoice(
                invoice,
                home_city,
                reimbursement_category=(link_by_invoice_id[invoice.pk].reimbursement_category if invoice.pk in link_by_invoice_id else None),
                trip_group_id=trip_group.pk if trip_group is not None else None,
            )
            for invoice in ordered_invoices
        ],
    }
    if trip_group is not None:
        summary.update({
            'id': trip_group.pk,
            'title': trip_group.title or build_default_trip_title(home_city, destination_places, trip_index, start_date, end_date),
            'source': trip_group.source,
            'manual_adjusted': trip_group.source == 'MANUAL',
            'home_city': trip_group.home_city or home_city,
        })
    else:
        summary.update({
            'title': build_default_trip_title(home_city, destination_places, trip_index, start_date, end_date),
        })
    return summary


def group_trip_invoice_sets(user: User, invoices: list[Invoice], explicit_home_city: str = '') -> dict:
    home_city = infer_home_city(user, explicit_home_city)
    sorted_invoices = sorted(invoices, key=lambda item: (timeline_sort_datetime(item), item.created_at, item.pk or 0))

    trip_invoice_groups: list[list[Invoice]] = []
    unmatched: list[Invoice] = []
    current_trip: list[Invoice] = []

    for invoice in sorted_invoices:
        if not timeline_sort_date(invoice) or not is_long_distance_transport(invoice):
            unmatched.append(invoice)
            continue

        departure_place = invoice.departure_place or ''
        arrival_place = invoice.arrival_place or ''
        if not departure_place or not arrival_place or not home_city:
            unmatched.append(invoice)
            continue

        is_depart_from_home = matches_home_city(departure_place, home_city)
        is_arrive_home = matches_home_city(arrival_place, home_city)

        if is_depart_from_home:
            if current_trip:
                trip_invoice_groups.append(current_trip)
            current_trip = [invoice]
            if is_arrive_home:
                trip_invoice_groups.append(current_trip)
                current_trip = []
            continue

        if current_trip:
            current_trip.append(invoice)
            if is_arrive_home:
                trip_invoice_groups.append(current_trip)
                current_trip = []
            continue

        unmatched.append(invoice)

    if current_trip:
        trip_invoice_groups.append(current_trip)

    return {
        'home_city': home_city,
        'trip_invoice_groups': trip_invoice_groups,
        'unmatched_invoices': unmatched,
    }


def group_trip_periods(user: User, invoices: list[Invoice], explicit_home_city: str = '') -> dict:
    grouped = group_trip_invoice_sets(user, invoices, explicit_home_city)
    return {
        'home_city': grouped['home_city'],
        'total_trips': len(grouped['trip_invoice_groups']),
        'trips': [
            build_trip_summary(grouped['home_city'], invoice_group, index + 1)
            for index, invoice_group in enumerate(grouped['trip_invoice_groups'])
        ],
        'unmatched_invoices': [
            serialize_trip_invoice(invoice, grouped['home_city'])
            for invoice in grouped['unmatched_invoices']
        ],
        'available_invoices': [
            serialize_trip_invoice(invoice, grouped['home_city'])
            for invoice in grouped['unmatched_invoices']
        ],
    }


def refresh_trip_group_summary(trip_group: TripGroup, invoices: list[Invoice] | None = None, home_city: str = '') -> None:
    if invoices is None:
        invoices = [
            link.invoice
            for link in TripGroupInvoice.objects.select_related('invoice')
            .filter(trip_group=trip_group)
            .order_by('sort_order', 'id')
        ]
    if not invoices:
        trip_group.delete()
        return

    effective_home_city = home_city or trip_group.home_city or infer_home_city(trip_group.user)
    summary = build_trip_summary(effective_home_city, invoices, 0)
    trip_group.home_city = effective_home_city
    trip_group.start_date = datetime.date.fromisoformat(summary['start_date']) if summary['start_date'] else None
    trip_group.end_date = datetime.date.fromisoformat(summary['end_date']) if summary['end_date'] else None
    trip_group.duration_days = summary['duration_days']
    trip_group.is_complete = summary['is_complete']
    trip_group.save(update_fields=['home_city', 'start_date', 'end_date', 'duration_days', 'is_complete', 'updated_at'])


def cleanup_empty_trip_groups(user: User) -> None:
    TripGroup.objects.filter(user=user, trip_group_invoices__isnull=True).delete()


def build_user_trip_summary(user: User, explicit_home_city: str = '') -> dict:
    home_city = infer_home_city(user, explicit_home_city)
    prefetch = Prefetch(
        'trip_group_invoices',
        queryset=TripGroupInvoice.objects.select_related('invoice').order_by('sort_order', 'id'),
    )
    groups = list(
        TripGroup.objects.filter(user=user)
        .prefetch_related(prefetch)
        .order_by('start_date', 'created_at', 'id')
    )
    trips = []
    for index, group in enumerate(groups, start=1):
        trip_links = list(
            TripGroupInvoice.objects.select_related('invoice')
            .filter(trip_group=group)
            .order_by('sort_order', 'id')
        )
        invoices = [link.invoice for link in trip_links]
        trips.append(build_trip_summary(group.home_city or home_city, invoices, index, trip_group=group, trip_links=trip_links))

    grouped_invoice_ids = TripGroupInvoice.objects.filter(trip_group__user=user).values_list('invoice_id', flat=True)
    available_invoices = list(
        Invoice.objects.filter(user=user)
        .exclude(id__in=grouped_invoice_ids)
        .order_by(Coalesce('service_start_date', 'invoice_date'), 'created_at', 'id')
    )
    return {
        'home_city': home_city,
        'total_trips': len(trips),
        'trips': trips,
        'unmatched_invoices': [serialize_trip_invoice(invoice, home_city) for invoice in available_invoices],
        'available_invoices': [serialize_trip_invoice(invoice, home_city) for invoice in available_invoices],
    }


@transaction.atomic
def regroup_auto_trip_groups(user: User, explicit_home_city: str = '') -> dict:
    home_city = infer_home_city(user, explicit_home_city)
    manual_invoice_ids = list(
        TripGroupInvoice.objects.filter(trip_group__user=user, trip_group__source='MANUAL').values_list('invoice_id', flat=True)
    )
    existing_auto_groups = list(
        TripGroup.objects.filter(user=user, source='AUTO').prefetch_related(
            Prefetch(
                'trip_group_invoices',
                queryset=TripGroupInvoice.objects.select_related('invoice').order_by('sort_order', 'id'),
                to_attr='prefetched_trip_group_invoices',
            )
        )
    )
    existing_title_by_signature = {
        build_trip_signature([link.invoice for link in getattr(group, 'prefetched_trip_group_invoices', [])]): (group.title or '')
        for group in existing_auto_groups
    }
    TripGroup.objects.filter(user=user, source='AUTO').delete()

    candidate_invoices = list(
        Invoice.objects.filter(user=user, invoice_type='TRANSPORT')
        .exclude(id__in=manual_invoice_ids)
        .order_by(Coalesce('service_start_date', 'invoice_date'), 'created_at', 'id')
    )
    grouped = group_trip_invoice_sets(user, candidate_invoices, home_city)
    for invoice_group in grouped['trip_invoice_groups']:
        signature = build_trip_signature(invoice_group)
        trip_group = TripGroup.objects.create(
            user=user,
            source='AUTO',
            title=existing_title_by_signature.get(signature) or None,
            home_city=grouped['home_city'],
        )
        TripGroupInvoice.objects.bulk_create([
            TripGroupInvoice(
                trip_group=trip_group,
                invoice=invoice,
                reimbursement_category=infer_reimbursement_category(invoice),
                sort_order=index,
            )
            for index, invoice in enumerate(invoice_group, start=1)
        ])
        refresh_trip_group_summary(trip_group, invoice_group, grouped['home_city'])

    cleanup_empty_trip_groups(user)
    return build_user_trip_summary(user, grouped['home_city'])


@transaction.atomic
def update_trip_group_title(user: User, trip_group: TripGroup, title: str) -> dict:
    if trip_group.user.pk != user.pk:
        raise ValidationError({'detail': '只能修改当前用户的行程组'})
    normalized_title = (title or '').strip()
    trip_group.title = normalized_title or None
    trip_group.save(update_fields=['title', 'updated_at'])
    return build_user_trip_summary(user, trip_group.home_city or '')


def validate_manual_trip_payload(
    user: User,
    invoice_ids: list[int],
    current_group: TripGroup | None = None,
) -> list[Invoice]:
    normalized_ids: list[int] = []
    for invoice_id in invoice_ids:
        try:
            normalized_id = int(invoice_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({'invoice_ids': '发票 ID 必须为整数'}) from exc
        if normalized_id not in normalized_ids:
            normalized_ids.append(normalized_id)

    if not normalized_ids:
        raise ValidationError({'invoice_ids': '至少选择一张票据'})

    invoices = list(
        Invoice.objects.filter(user=user, id__in=normalized_ids)
    )
    invoice_map = {invoice.pk: invoice for invoice in invoices}
    missing_ids = [invoice_id for invoice_id in normalized_ids if invoice_id not in invoice_map]
    if missing_ids:
        raise ValidationError({'invoice_ids': f'以下发票不存在或不属于当前用户: {missing_ids}'})

    manual_conflicts = TripGroupInvoice.objects.filter(
        invoice_id__in=normalized_ids,
        trip_group__user=user,
        trip_group__source='MANUAL',
    )
    if current_group is not None:
        manual_conflicts = manual_conflicts.exclude(trip_group=current_group)
    conflict_ids = list(manual_conflicts.values_list('invoice_id', flat=True))
    if conflict_ids:
        raise ValidationError({'invoice_ids': f'以下发票已在其他手动行程组中: {conflict_ids}'})

    return [invoice_map[invoice_id] for invoice_id in normalized_ids]


@transaction.atomic
def save_manual_trip_group(
    user: User,
    invoice_ids: list[int],
    home_city: str = '',
    trip_group: TripGroup | None = None,
) -> TripGroup:
    invoices = validate_manual_trip_payload(user, invoice_ids, trip_group)
    effective_home_city = infer_home_city(user, home_city)

    TripGroupInvoice.objects.filter(
        invoice_id__in=[invoice.pk for invoice in invoices],
        trip_group__user=user,
        trip_group__source='AUTO',
    ).delete()
    cleanup_empty_trip_groups(user)

    if trip_group is None:
        trip_group = TripGroup.objects.create(
            user=user,
            source='MANUAL',
            home_city=effective_home_city,
        )
    else:
        if trip_group.user.pk != user.pk or trip_group.source != 'MANUAL':
            raise ValidationError({'detail': '只能修改当前用户的手动行程组'})
        trip_group.home_city = effective_home_city
        trip_group.save(update_fields=['home_city', 'updated_at'])
        TripGroupInvoice.objects.filter(trip_group=trip_group).exclude(
            invoice_id__in=[invoice.pk for invoice in invoices]
        ).delete()

    for index, invoice in enumerate(invoices, start=1):
        TripGroupInvoice.objects.update_or_create(
            invoice=invoice,
            defaults={
                'trip_group': trip_group,
                'reimbursement_category': infer_reimbursement_category(invoice),
                'sort_order': index,
            },
        )

    refresh_trip_group_summary(trip_group, invoices, effective_home_city)
    regroup_auto_trip_groups(user, effective_home_city)
    trip_group.refresh_from_db()
    return trip_group


@transaction.atomic
def delete_manual_trip_group(user: User, trip_group: TripGroup) -> None:
    if trip_group.user.pk != user.pk or trip_group.source != 'MANUAL':
        raise ValidationError({'detail': '只能删除当前用户的手动行程组'})
    home_city = trip_group.home_city or infer_home_city(user)
    trip_group.delete()
    regroup_auto_trip_groups(user, home_city)


@transaction.atomic
def attach_invoice_to_trip_group(
    user: User,
    trip_group: TripGroup,
    invoice_id: int,
    reimbursement_category: str,
) -> dict:
    if trip_group.user.pk != user.pk:
        raise ValidationError({'detail': '只能修改当前用户的行程组'})

    invoice = Invoice.objects.filter(user=user, pk=invoice_id).first()
    if invoice is None:
        raise ValidationError({'invoice_id': '票据不存在'})
    if reimbursement_category not in {'TRANSPORT', 'ACCOMMODATION', 'OTHER'}:
        raise ValidationError({'reimbursement_category': '票据类型无效'})

    existing_link = TripGroupInvoice.objects.filter(invoice=invoice).first()
    if existing_link and existing_link.trip_group.pk != trip_group.pk:
        existing_link.delete()
        TripGroup.objects.filter(user=user, source='AUTO', trip_group_invoices__isnull=True).delete()

    if trip_group.source == 'AUTO':
        trip_group.source = 'MANUAL'
        trip_group.save(update_fields=['source', 'updated_at'])

    max_sort_order = (
        TripGroupInvoice.objects.filter(trip_group=trip_group).order_by('-sort_order').values_list('sort_order', flat=True).first()
        or 0
    )
    TripGroupInvoice.objects.update_or_create(
        invoice=invoice,
        defaults={
            'trip_group': trip_group,
            'reimbursement_category': reimbursement_category,
            'sort_order': max_sort_order + 1,
        },
    )
    refresh_trip_group_summary(trip_group, home_city=trip_group.home_city or infer_home_city(user))
    return build_user_trip_summary(user, trip_group.home_city or '')


@transaction.atomic
def update_trip_group_invoice_category(
    user: User,
    trip_group: TripGroup,
    invoice_id: int,
    reimbursement_category: str,
) -> dict:
    if reimbursement_category not in {'TRANSPORT', 'ACCOMMODATION', 'OTHER'}:
        raise ValidationError({'reimbursement_category': '票据类型无效'})
    trip_link = TripGroupInvoice.objects.filter(trip_group=trip_group, invoice_id=invoice_id).select_related('invoice').first()
    if trip_link is None or trip_group.user.pk != user.pk:
        raise ValidationError({'invoice_id': '行程票据不存在'})
    trip_link.reimbursement_category = reimbursement_category
    trip_link.save(update_fields=['reimbursement_category'])
    return build_user_trip_summary(user, trip_group.home_city or '')


@transaction.atomic
def remove_invoice_from_trip_group(user: User, trip_group: TripGroup, invoice_id: int) -> dict:
    if trip_group.user.pk != user.pk:
        raise ValidationError({'detail': '只能修改当前用户的行程组'})
    trip_link = TripGroupInvoice.objects.filter(trip_group=trip_group, invoice_id=invoice_id).select_related('invoice').first()
    if trip_link is None:
        raise ValidationError({'invoice_id': '行程票据不存在'})
    trip_link.delete()
    refresh_trip_group_summary(trip_group, home_city=trip_group.home_city or infer_home_city(user))
    return build_user_trip_summary(user, trip_group.home_city or '')


def build_timeline(user: User) -> dict:
    """构建融合行程时间线：火车/机票切分行程段，网约车按行程单附件时间插入时间线。"""
    all_transport = list(
        Invoice.objects.filter(user=user, invoice_type='TRANSPORT')
        .prefetch_related(Prefetch('attachments', to_attr='prefetched_attachments'))
        .order_by(Coalesce('service_start_date', 'invoice_date'), 'created_at', 'id')
    )
    timeline_transport_invoices = sorted(
        [inv for inv in all_transport if is_long_distance_transport(inv) or has_ride_hailing_trip_statement(inv)],
        key=lambda inv: (timeline_sort_datetime(inv), inv.created_at, inv.pk or 0),
    )
    separators = list(
        TripSeparator.objects.filter(user=user)
        .select_related('after_invoice')
        .order_by('after_invoice__invoice_date', 'created_at', 'id')
    )

    home_city = infer_home_city(user)

    sep_by_after_id: dict[int, TripSeparator] = {}
    for sep in separators:
        if sep.after_invoice_id is not None:
            sep_by_after_id[sep.after_invoice_id] = sep

    segments: list[dict] = []
    current_segment: list[Invoice] = []

    for invoice in timeline_transport_invoices:
        current_segment.append(invoice)

        if not is_long_distance_transport(invoice):
            continue

        close_reason: str | None = None
        has_manual_sep = invoice.pk in sep_by_after_id
        is_arrive_home = matches_home_city(invoice.arrival_place or '', home_city)

        if has_manual_sep and is_arrive_home:
            close_reason = 'both'
        elif has_manual_sep:
            close_reason = 'manual'
        elif is_arrive_home:
            close_reason = 'auto'

        if close_reason:
            segments.append({
                'invoices': list(current_segment),
                'close_reason': close_reason,
                'separator': sep_by_after_id.get(invoice.pk),
            })
            current_segment = []

    if current_segment:
        segments.append({
            'invoices': list(current_segment),
            'close_reason': None,
            'separator': None,
        })

    if not segments and timeline_transport_invoices:
        segments = [{
            'invoices': list(timeline_transport_invoices),
            'close_reason': None,
            'separator': None,
        }]

    serialized_separators = []
    for sep in separators:
        after_invoice = sep.after_invoice
        serialized_separators.append({
            'id': sep.pk,
            'after_invoice_id': after_invoice.pk if after_invoice else None,
            'after_invoice_number': after_invoice.invoice_number if after_invoice else None,
            'after_invoice_date': after_invoice.invoice_date.isoformat() if after_invoice and after_invoice.invoice_date else None,
            'label': sep.label or '',
            'created_at': sep.created_at.isoformat() if sep.created_at else None,
        })

    serialized_segments = []
    for index, seg in enumerate(segments, start=1):
        seg_invoices = seg['invoices']
        trip_group_id = None
        if seg_invoices:
            trip_group_id = (
                TripGroupInvoice.objects.filter(
                    trip_group__user=user,
                    invoice_id__in=[invoice.pk for invoice in seg_invoices if invoice.pk is not None],
                )
                .order_by('trip_group__source', 'trip_group_id')
                .values_list('trip_group_id', flat=True)
                .first()
            )
        start_date = timeline_sort_date(seg_invoices[0]) if seg_invoices else None
        end_date = timeline_sort_date(seg_invoices[-1]) if seg_invoices else None
        serialized_segments.append({
            'segment_no': index,
            'trip_group_id': trip_group_id,
            'start_date': start_date.isoformat() if start_date else None,
            'end_date': end_date.isoformat() if end_date else None,
            'invoice_count': len(seg_invoices),
            'close_reason': seg['close_reason'],
            'is_open': seg['close_reason'] is None,
            'invoices': [
                serialize_trip_invoice(invoice, home_city)
                for invoice in seg_invoices
            ],
        })

    all_invoices_serialized = []
    boundary_ids: set[int] = set()
    for seg in segments:
        seg_invoices = seg['invoices']
        if seg_invoices:
            last_id = seg_invoices[-1].pk
            if last_id is not None:
                boundary_ids.add(last_id)

    for invoice in timeline_transport_invoices:
        data = serialize_trip_invoice(invoice, home_city)
        data['is_segment_end'] = invoice.pk in boundary_ids
        data['segment_end_reason'] = None
        if data['is_segment_end']:
            for seg in segments:
                if seg['invoices'] and seg['invoices'][-1].pk == invoice.pk:
                    data['segment_end_reason'] = seg['close_reason']
                    break
        all_invoices_serialized.append(data)

    available_invoices = [
        serialize_trip_invoice(inv, home_city)
        for inv in all_transport
        if not is_long_distance_transport(inv) and not has_ride_hailing_trip_statement(inv)
    ]
    other_invoices = list(
        Invoice.objects.filter(user=user)
        .exclude(invoice_type='TRANSPORT')
        .order_by('invoice_date', 'created_at', 'id')
    )
    for inv in other_invoices:
        available_invoices.append(serialize_trip_invoice(inv, home_city))

    return {
        'home_city': home_city,
        'total_invoices': len(timeline_transport_invoices),
        'total_separators': len(separators),
        'total_segments': len(segments),
        'separators': serialized_separators,
        'segments': serialized_segments,
        'all_invoices': all_invoices_serialized,
        'available_invoices': available_invoices,
    }


@transaction.atomic
def insert_separator(user: User, after_invoice_id: int | None, label: str = '') -> dict:
    after_invoice = None
    if after_invoice_id is not None:
        after_invoice = Invoice.objects.filter(user=user, pk=after_invoice_id).first()
        if after_invoice is None:
            raise ValidationError({'after_invoice_id': '发票不存在或不属于当前用户'})

    TripSeparator.objects.create(
        user=user,
        after_invoice=after_invoice,
        label=(label or '').strip() or None,
    )
    return build_timeline(user)


@transaction.atomic
def delete_separator(user: User, separator_id: int) -> dict:
    separator = TripSeparator.objects.filter(user=user, pk=separator_id).first()
    if separator is None:
        raise ValidationError({'separator_id': '分隔符不存在或不属于当前用户'})
    separator.delete()
    return build_timeline(user)
