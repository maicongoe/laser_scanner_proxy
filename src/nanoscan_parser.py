from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None


_DATAGRAM_HEADER_SIZE = 24
_DATA_HEADER_SIZE = 52
_ANGLE_RESOLUTION = 4_194_304.0
_MAX_BEAMS = 2_751


@dataclass(frozen=True)
class NanoScanSnapshot:
    sequence_number: int
    scan_number: int
    channel_number: int
    timestamp_date: int
    timestamp_time: int
    number_of_beams: int
    multiplication_factor: int
    scan_time_ms: int
    interbeam_period_us: int
    start_angle_deg: float
    angular_beam_resolution_deg: float
    valid_beams: Optional[int]
    infinite_beams: Optional[int]
    glare_beams: Optional[int]
    reflector_beams: Optional[int]
    contamination_beams: Optional[int]
    contamination_warning_beams: Optional[int]
    min_range_m: Optional[float]
    max_range_m: Optional[float]
    sample_step: int
    sample_angles_deg: list[float]
    sample_ranges_m: list[Optional[float]]
    sample_reflectivity: list[int]

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence_number": self.sequence_number,
            "scan_number": self.scan_number,
            "channel_number": self.channel_number,
            "timestamp_date": self.timestamp_date,
            "timestamp_time": self.timestamp_time,
            "number_of_beams": self.number_of_beams,
            "multiplication_factor": self.multiplication_factor,
            "scan_time_ms": self.scan_time_ms,
            "interbeam_period_us": self.interbeam_period_us,
            "start_angle_deg": round(self.start_angle_deg, 6),
            "angular_beam_resolution_deg": round(self.angular_beam_resolution_deg, 6),
            "valid_beams": self.valid_beams,
            "infinite_beams": self.infinite_beams,
            "glare_beams": self.glare_beams,
            "reflector_beams": self.reflector_beams,
            "contamination_beams": self.contamination_beams,
            "contamination_warning_beams": self.contamination_warning_beams,
            "min_range_m": None if self.min_range_m is None else round(self.min_range_m, 4),
            "max_range_m": None if self.max_range_m is None else round(self.max_range_m, 4),
            "sample_step": self.sample_step,
            "sample_angles_deg": [round(value, 4) for value in self.sample_angles_deg],
            "sample_ranges_m": [
                None if value is None else round(value, 4) for value in self.sample_ranges_m
            ],
            "sample_reflectivity": self.sample_reflectivity,
        }


@dataclass
class _ReassemblyBuffer:
    total_length: int
    payload: bytearray
    fragments: dict[int, int]
    received_bytes: int
    last_update_monotonic: float


class _DatagramReassembler:
    def __init__(self, timeout_sec: float = 1.0, max_packet_size: int = 512_000) -> None:
        self._timeout_sec = timeout_sec
        self._max_packet_size = max_packet_size
        self._buffers: dict[int, _ReassemblyBuffer] = {}

    def add_fragment(self, datagram: memoryview, now_monotonic: float) -> Optional[bytes]:
        self._drop_expired(now_monotonic)
        if len(datagram) < _DATAGRAM_HEADER_SIZE:
            return None

        total_length = struct.unpack_from("<I", datagram, 8)[0]
        identification = struct.unpack_from("<I", datagram, 12)[0]
        fragment_offset = struct.unpack_from("<I", datagram, 16)[0]

        if total_length == 0 or total_length > self._max_packet_size:
            return None
        if fragment_offset >= total_length:
            return None

        payload = datagram[_DATAGRAM_HEADER_SIZE:]
        if not payload:
            return None

        end_offset = min(total_length, fragment_offset + len(payload))
        copy_length = end_offset - fragment_offset
        if copy_length <= 0:
            return None

        current = self._buffers.get(identification)
        if current is None or current.total_length != total_length:
            current = _ReassemblyBuffer(
                total_length=total_length,
                payload=bytearray(total_length),
                fragments={},
                received_bytes=0,
                last_update_monotonic=now_monotonic,
            )
            self._buffers[identification] = current

        current.payload[fragment_offset:end_offset] = payload[:copy_length]
        previous_length = current.fragments.get(fragment_offset, 0)
        if copy_length > previous_length:
            current.received_bytes += (copy_length - previous_length)
            current.fragments[fragment_offset] = copy_length
        current.last_update_monotonic = now_monotonic

        if current.received_bytes >= total_length:
            full_packet = bytes(current.payload)
            del self._buffers[identification]
            return full_packet
        return None

    def _drop_expired(self, now_monotonic: float) -> None:
        stale_ids = [
            ident
            for ident, buffer in self._buffers.items()
            if now_monotonic - buffer.last_update_monotonic > self._timeout_sec
        ]
        for ident in stale_ids:
            del self._buffers[ident]


class NanoScanUdpInterpreter:
    def __init__(self, max_sample_points: int = 120) -> None:
        self._reassembler = _DatagramReassembler()
        self._max_sample_points = max(1, max_sample_points)
        self._has_numpy = np is not None

    def feed_datagram(
        self,
        datagram: memoryview,
        now_monotonic: float,
        parse_enabled: bool = True,
        full_parse: bool = True,
    ) -> Optional[NanoScanSnapshot]:
        payload = self._reassembler.add_fragment(datagram, now_monotonic)
        if payload is None:
            return None
        if not parse_enabled:
            return None
        return self._parse_payload(payload, full_parse=full_parse)

    def _parse_payload(self, payload: bytes, full_parse: bool) -> Optional[NanoScanSnapshot]:
        if len(payload) < _DATA_HEADER_SIZE:
            return None

        channel_number = payload[12]
        sequence_number = struct.unpack_from("<I", payload, 16)[0]
        scan_number = struct.unpack_from("<I", payload, 20)[0]
        timestamp_date = struct.unpack_from("<H", payload, 24)[0]
        timestamp_time = struct.unpack_from("<I", payload, 28)[0]

        derived_offset = struct.unpack_from("<H", payload, 36)[0]
        derived_size = struct.unpack_from("<H", payload, 38)[0]
        measurement_offset = struct.unpack_from("<H", payload, 40)[0]
        measurement_size = struct.unpack_from("<H", payload, 42)[0]

        if not self._is_block_valid(derived_offset, derived_size, len(payload)):
            return None
        if not self._is_block_valid(measurement_offset, measurement_size, len(payload)):
            return None

        multiplication_factor = struct.unpack_from("<H", payload, derived_offset + 0)[0]
        scan_time_ms = struct.unpack_from("<H", payload, derived_offset + 4)[0]
        start_angle_raw = struct.unpack_from("<i", payload, derived_offset + 8)[0]
        angular_resolution_raw = struct.unpack_from("<i", payload, derived_offset + 12)[0]
        interbeam_period_us = struct.unpack_from("<I", payload, derived_offset + 16)[0]

        start_angle_deg = start_angle_raw / _ANGLE_RESOLUTION
        angular_resolution_deg = angular_resolution_raw / _ANGLE_RESOLUTION

        number_of_beams_field = struct.unpack_from("<I", payload, measurement_offset + 0)[0]
        max_by_block = max(0, (measurement_size - 4) // 4)
        max_by_payload = max(0, (len(payload) - measurement_offset - 4) // 4)
        number_of_beams = min(number_of_beams_field, max_by_block, max_by_payload, _MAX_BEAMS)

        if number_of_beams <= 0:
            return None

        sample_step = max(1, int(math.ceil(number_of_beams / self._max_sample_points)))

        (
            valid_beams,
            infinite_beams,
            glare_beams,
            reflector_beams,
            contamination_beams,
            contamination_warning_beams,
            min_range_m,
            max_range_m,
            sample_angles_deg,
            sample_ranges_m,
            sample_reflectivity,
        ) = self._extract_measurement(
            payload=payload,
            measurement_offset=measurement_offset,
            number_of_beams=number_of_beams,
            multiplication_factor=multiplication_factor,
            start_angle_deg=start_angle_deg,
            angular_resolution_deg=angular_resolution_deg,
            sample_step=sample_step,
            full_parse=full_parse,
        )

        return NanoScanSnapshot(
            sequence_number=sequence_number,
            scan_number=scan_number,
            channel_number=channel_number,
            timestamp_date=timestamp_date,
            timestamp_time=timestamp_time,
            number_of_beams=number_of_beams,
            multiplication_factor=multiplication_factor,
            scan_time_ms=scan_time_ms,
            interbeam_period_us=interbeam_period_us,
            start_angle_deg=start_angle_deg,
            angular_beam_resolution_deg=angular_resolution_deg,
            valid_beams=valid_beams,
            infinite_beams=infinite_beams,
            glare_beams=glare_beams,
            reflector_beams=reflector_beams,
            contamination_beams=contamination_beams,
            contamination_warning_beams=contamination_warning_beams,
            min_range_m=min_range_m,
            max_range_m=max_range_m,
            sample_step=sample_step,
            sample_angles_deg=sample_angles_deg,
            sample_ranges_m=sample_ranges_m,
            sample_reflectivity=sample_reflectivity,
        )

    def _extract_measurement(
        self,
        payload: bytes,
        measurement_offset: int,
        number_of_beams: int,
        multiplication_factor: int,
        start_angle_deg: float,
        angular_resolution_deg: float,
        sample_step: int,
        full_parse: bool,
    ) -> tuple[
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[float],
        Optional[float],
        list[float],
        list[Optional[float]],
        list[int],
    ]:
        if self._has_numpy:
            return self._extract_measurement_numpy(
                payload=payload,
                measurement_offset=measurement_offset,
                number_of_beams=number_of_beams,
                multiplication_factor=multiplication_factor,
                start_angle_deg=start_angle_deg,
                angular_resolution_deg=angular_resolution_deg,
                sample_step=sample_step,
                full_parse=full_parse,
            )
        return self._extract_measurement_python(
            payload=payload,
            measurement_offset=measurement_offset,
            number_of_beams=number_of_beams,
            multiplication_factor=multiplication_factor,
            start_angle_deg=start_angle_deg,
            angular_resolution_deg=angular_resolution_deg,
            sample_step=sample_step,
            full_parse=full_parse,
        )

    def _extract_measurement_numpy(
        self,
        payload: bytes,
        measurement_offset: int,
        number_of_beams: int,
        multiplication_factor: int,
        start_angle_deg: float,
        angular_resolution_deg: float,
        sample_step: int,
        full_parse: bool,
    ) -> tuple[
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[float],
        Optional[float],
        list[float],
        list[Optional[float]],
        list[int],
    ]:
        assert np is not None
        beam_array = np.frombuffer(
            payload,
            dtype=np.dtype([("distance", "<u2"), ("reflectivity", "u1"), ("status", "u1")]),
            count=number_of_beams,
            offset=measurement_offset + 4,
        )
        status = beam_array["status"]
        reflectivity = beam_array["reflectivity"]
        distance_m = beam_array["distance"].astype(np.float32) * (multiplication_factor * 0.001)

        infinite_mask = (status & 0x02) != 0

        if full_parse:
            valid_mask = (status & 0x01) != 0
            glare_mask = (status & 0x04) != 0
            reflector_mask = (status & 0x08) != 0
            contamination_mask = (status & 0x10) != 0
            contamination_warning_mask = (status & 0x20) != 0

            valid_beams: Optional[int] = int(np.count_nonzero(valid_mask))
            infinite_beams: Optional[int] = int(np.count_nonzero(infinite_mask))
            glare_beams: Optional[int] = int(np.count_nonzero(glare_mask))
            reflector_beams: Optional[int] = int(np.count_nonzero(reflector_mask))
            contamination_beams: Optional[int] = int(np.count_nonzero(contamination_mask))
            contamination_warning_beams: Optional[int] = int(
                np.count_nonzero(contamination_warning_mask)
            )

            finite_valid_mask = valid_mask & (~infinite_mask)
            if np.any(finite_valid_mask):
                min_range_m: Optional[float] = float(distance_m[finite_valid_mask].min())
                max_range_m: Optional[float] = float(distance_m[finite_valid_mask].max())
            else:
                min_range_m = None
                max_range_m = None
        else:
            valid_beams = None
            infinite_beams = None
            glare_beams = None
            reflector_beams = None
            contamination_beams = None
            contamination_warning_beams = None
            finite_mask = ~infinite_mask
            if np.any(finite_mask):
                min_range_m = float(distance_m[finite_mask].min())
                max_range_m = float(distance_m[finite_mask].max())
            else:
                min_range_m = None
                max_range_m = None

        sample_indices = np.arange(0, number_of_beams, sample_step, dtype=np.int32)
        if sample_indices.size == 0:
            sample_indices = np.array([0], dtype=np.int32)
        if sample_indices[-1] != (number_of_beams - 1):
            sample_indices = np.append(sample_indices, number_of_beams - 1)

        sample_angles_np = start_angle_deg + (sample_indices.astype(np.float32) * angular_resolution_deg)
        sampled_infinite = infinite_mask[sample_indices]
        sampled_ranges = distance_m[sample_indices]
        sample_reflect = reflectivity[sample_indices]

        sample_angles_deg = sample_angles_np.astype(np.float32).tolist()
        sample_ranges_m = [
            None if bool(is_inf) else float(value)
            for is_inf, value in zip(sampled_infinite.tolist(), sampled_ranges.tolist())
        ]
        sample_reflectivity = sample_reflect.astype(np.uint8).tolist()

        return (
            valid_beams,
            infinite_beams,
            glare_beams,
            reflector_beams,
            contamination_beams,
            contamination_warning_beams,
            min_range_m,
            max_range_m,
            sample_angles_deg,
            sample_ranges_m,
            sample_reflectivity,
        )

    def _extract_measurement_python(
        self,
        payload: bytes,
        measurement_offset: int,
        number_of_beams: int,
        multiplication_factor: int,
        start_angle_deg: float,
        angular_resolution_deg: float,
        sample_step: int,
        full_parse: bool,
    ) -> tuple[
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[int],
        Optional[float],
        Optional[float],
        list[float],
        list[Optional[float]],
        list[int],
    ]:
        sample_angles_deg: list[float] = []
        sample_ranges_m: list[Optional[float]] = []
        sample_reflectivity: list[int] = []

        valid_beams = 0 if full_parse else None
        infinite_beams = 0 if full_parse else None
        glare_beams = 0 if full_parse else None
        reflector_beams = 0 if full_parse else None
        contamination_beams = 0 if full_parse else None
        contamination_warning_beams = 0 if full_parse else None
        min_range_m: Optional[float] = None
        max_range_m: Optional[float] = None

        for index in range(number_of_beams):
            base = measurement_offset + 4 + (index * 4)
            distance_raw = struct.unpack_from("<H", payload, base + 0)[0]
            reflectivity = payload[base + 2]
            status = payload[base + 3]

            valid = bool(status & (1 << 0))
            infinite = bool(status & (1 << 1))
            glare = bool(status & (1 << 2))
            reflector = bool(status & (1 << 3))
            contamination = bool(status & (1 << 4))
            contamination_warning = bool(status & (1 << 5))

            if full_parse:
                if valid_beams is not None and valid:
                    valid_beams += 1
                if infinite_beams is not None and infinite:
                    infinite_beams += 1
                if glare_beams is not None and glare:
                    glare_beams += 1
                if reflector_beams is not None and reflector:
                    reflector_beams += 1
                if contamination_beams is not None and contamination:
                    contamination_beams += 1
                if contamination_warning_beams is not None and contamination_warning:
                    contamination_warning_beams += 1

            range_m: Optional[float] = None if infinite else (distance_raw * multiplication_factor) * 0.001
            if range_m is not None and (full_parse is False or valid):
                min_range_m = range_m if min_range_m is None else min(min_range_m, range_m)
                max_range_m = range_m if max_range_m is None else max(max_range_m, range_m)

            if index % sample_step == 0 or index == (number_of_beams - 1):
                sample_angles_deg.append(start_angle_deg + (index * angular_resolution_deg))
                sample_ranges_m.append(range_m)
                sample_reflectivity.append(reflectivity)

        return (
            valid_beams,
            infinite_beams,
            glare_beams,
            reflector_beams,
            contamination_beams,
            contamination_warning_beams,
            min_range_m,
            max_range_m,
            sample_angles_deg,
            sample_ranges_m,
            sample_reflectivity,
        )

    @staticmethod
    def _is_block_valid(offset: int, size: int, payload_size: int) -> bool:
        if offset == 0 and size == 0:
            return False
        if size <= 0:
            return False
        end = offset + size
        return offset >= 0 and end <= payload_size
