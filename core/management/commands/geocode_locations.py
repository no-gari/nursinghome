import time
import requests
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from core.models import Facility, Hospital


class Command(BaseCommand):
    help = 'Geocode addresses for Facility and Hospital models using Google Geocoding API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--model',
            type=str,
            choices=['facility', 'hospital', 'both'],
            default='both',
            help='Which model to geocode (facility, hospital, or both)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit the number of records to process'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force geocoding even if coordinates already exist'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=0.1,
            help='Delay between API requests in seconds (default: 0.1)'
        )

    def handle(self, *args, **options):
        # Google Geocoding API 키 확인
        google_api_key = 'AIzaSyBKyJT20ZuyRM7Otpunpps2cyJFEG9gKyM'
        if not google_api_key:
            raise CommandError(
                'GOOGLE_GEOCODING_API_KEY not found in settings. '
                'Please add your Google Geocoding API key to settings.py'
            )

        model_choice = options['model']
        limit = options['limit']
        force = options['force']
        delay = options['delay']

        if model_choice in ['facility', 'both']:
            self.geocode_facilities(google_api_key, limit, force, delay)

        if model_choice in ['hospital', 'both']:
            self.geocode_hospitals(google_api_key, limit, force, delay)

    def geocode_facilities(self, api_key, limit, force, delay):
        """Facility 모델의 주소를 좌표로 변환"""
        self.stdout.write(self.style.SUCCESS('Starting geocoding for Facilities...'))

        # 좌표가 없거나 force 옵션이 True인 경우 필터링
        if force:
            facilities = Facility.objects.exclude(location='')
        else:
            facilities = Facility.objects.filter(
                location__isnull=False
            ).exclude(location='').filter(
                latitude__isnull=True, longitude__isnull=True
            )

        if limit:
            facilities = facilities[:limit]

        total_count = facilities.count()
        self.stdout.write(f'Found {total_count} facilities to geocode')

        success_count = 0
        error_count = 0

        for i, facility in enumerate(facilities, 1):
            try:
                self.stdout.write(f'[{i}/{total_count}] Processing: {facility.name}')

                lat, lng = self.get_coordinates(api_key, facility.location)

                if lat and lng:
                    facility.latitude = Decimal(str(lat))
                    facility.longitude = Decimal(str(lng))
                    facility.save(update_fields=['latitude', 'longitude'])
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Updated coordinates: {lat}, {lng}')
                    )
                else:
                    error_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'  ✗ Could not geocode address: {facility.location}')
                    )

                # API 호출 제한을 위한 지연
                if delay > 0:
                    time.sleep(delay)

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error processing {facility.name}: {str(e)}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Facility geocoding completed. Success: {success_count}, Errors: {error_count}'
            )
        )

    def geocode_hospitals(self, api_key, limit, force, delay):
        """Hospital 모델의 주소를 좌표로 변환"""
        self.stdout.write(self.style.SUCCESS('Starting geocoding for Hospitals...'))

        # 좌표가 없거나 force 옵션이 True인 경우 필터링
        if force:
            hospitals = Hospital.objects.exclude(location='')
        else:
            hospitals = Hospital.objects.filter(
                location__isnull=False
            ).exclude(location='').filter(
                latitude__isnull=True, longitude__isnull=True
            )

        if limit:
            hospitals = hospitals[:limit]

        total_count = hospitals.count()
        self.stdout.write(f'Found {total_count} hospitals to geocode')

        success_count = 0
        error_count = 0

        for i, hospital in enumerate(hospitals, 1):
            try:
                self.stdout.write(f'[{i}/{total_count}] Processing: {hospital.name}')

                lat, lng = self.get_coordinates(api_key, hospital.location)

                if lat and lng:
                    hospital.latitude = Decimal(str(lat))
                    hospital.longitude = Decimal(str(lng))
                    hospital.save(update_fields=['latitude', 'longitude'])
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Updated coordinates: {lat}, {lng}')
                    )
                else:
                    error_count += 1
                    self.stdout.write(
                        self.style.WARNING(f'  ✗ Could not geocode address: {hospital.location}')
                    )

                # API 호출 제한을 위한 지연
                if delay > 0:
                    time.sleep(delay)

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ Error processing {hospital.name}: {str(e)}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Hospital geocoding completed. Success: {success_count}, Errors: {error_count}'
            )
        )

    def get_coordinates(self, api_key, address):
        """Google Geocoding API를 사용하여 주소를 좌표로 변환"""
        if not address or not address.strip():
            return None, None

        url = 'https://maps.googleapis.com/maps/api/geocode/json'
        params = {
            'address': address.strip(),
            'key': api_key,
            'region': 'kr',  # 한국 지역 우선
            'language': 'ko'  # 한국어 응답
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            # API 상태 확인
            if data.get('status') == 'OK' and data.get('results'):
                # 첫 번�� 결과 사용
                result = data['results'][0]
                location = result['geometry']['location']
                latitude = float(location['lat'])
                longitude = float(location['lng'])
                return latitude, longitude
            elif data.get('status') == 'ZERO_RESULTS':
                self.stdout.write(
                    self.style.WARNING(f'No results found for address: {address}')
                )
                return None, None
            elif data.get('status') == 'OVER_QUERY_LIMIT':
                self.stdout.write(
                    self.style.ERROR(f'API quota exceeded. Please check your usage.')
                )
                return None, None
            elif data.get('status') == 'REQUEST_DENIED':
                self.stdout.write(
                    self.style.ERROR(f'API request denied. Please check your API key.')
                )
                return None, None
            else:
                self.stdout.write(
                    self.style.WARNING(f'API returned status: {data.get("status")} for address: {address}')
                )
                return None, None

        except requests.exceptions.RequestException as e:
            self.stdout.write(
                self.style.ERROR(f'API request failed for address "{address}": {str(e)}')
            )
            return None, None
        except (KeyError, ValueError, TypeError) as e:
            self.stdout.write(
                self.style.ERROR(f'Error parsing response for address "{address}": {str(e)}')
            )
            return None, None
