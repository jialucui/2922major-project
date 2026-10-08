"""Async BLE client isolated from the GUI thread."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future
import threading

from bleak import BleakClient, BleakScanner
from PySide6.QtCore import QObject, Signal

from .protocol import (
    CONTROL_CHARACTERISTIC_UUID,
    DATA_CHARACTERISTIC_UUID,
    SERVICE_UUID,
    FragmentAssembler,
    ProtocolError,
    decode_packet,
    encode_set_recording,
)


class BluetoothWorker(QObject):
    devices_found = Signal(list)
    connection_changed = Signal(bool, str)
    packet_received = Signal(object)
    error_occurred = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = threading.Thread(target=self._run_event_loop, name="ppg-ble", daemon=True)
        self._ready = threading.Event()
        self._client: BleakClient | None = None
        self._assembler = FragmentAssembler()
        self._stopping = False

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()
        self._ready.wait(timeout=3)

    def _run_event_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    def scan(self) -> None:
        self._schedule(self._scan())

    async def _scan(self) -> None:
        try:
            devices = await BleakScanner.discover(timeout=5.0)
            found = [
                {"name": device.name or "Unnamed BLE device", "address": device.address, "rssi": device.rssi}
                for device in devices
            ]
            self.devices_found.emit(found)
        except Exception as error:
            self.error_occurred.emit(f"BLE scan failed: {error}")

    def connect_to(self, address: str) -> None:
        self._schedule(self._connect(address))

    async def _connect(self, address: str) -> None:
        await self._disconnect()
        client = BleakClient(address, disconnected_callback=self._on_disconnected)
        try:
            await client.connect()
            if not client.is_connected:
                raise ConnectionError("BLE connection did not complete")
            await client.start_notify(DATA_CHARACTERISTIC_UUID, self._on_notification)
            self._client = client
            self._assembler.reset()
            self.connection_changed.emit(True, address)
        except Exception as error:
            try:
                await client.disconnect()
            except Exception:
                pass
            self._client = None
            self.connection_changed.emit(False, "")
            self.error_occurred.emit(f"BLE connection failed: {error}")

    async def _disconnect(self) -> None:
        client = self._client
        self._client = None
        self._assembler.reset()
        if client is not None and client.is_connected:
            try:
                await client.stop_notify(DATA_CHARACTERISTIC_UUID)
            except Exception:
                pass
            await client.disconnect()
        self.connection_changed.emit(False, "")

    def disconnect(self) -> None:
        self._schedule(self._disconnect())

    def set_recording(self, enabled: bool) -> None:
        self._schedule(self._write_control(encode_set_recording(enabled)))

    async def _write_control(self, command: bytes) -> None:
        client = self._client
        if client is None or not client.is_connected:
            self.error_occurred.emit("Cannot change recording state while disconnected")
            return
        try:
            await client.write_gatt_char(CONTROL_CHARACTERISTIC_UUID, command, response=True)
        except Exception as error:
            self.error_occurred.emit(f"BLE control write failed: {error}")

    def _on_notification(self, _sender: int, data: bytearray) -> None:
        try:
            frame = self._assembler.feed(bytes(data))
            if frame is not None:
                self.packet_received.emit(decode_packet(frame))
        except ProtocolError as error:
            self.error_occurred.emit(f"Invalid BLE packet: {error}")

    def _on_disconnected(self, _client: BleakClient) -> None:
        self._client = None
        self._assembler.reset()
        self.connection_changed.emit(False, "")

    def _schedule(self, coroutine) -> Future | None:
        loop = self._loop
        if loop is None or not loop.is_running() or self._stopping:
            coroutine.close()
            self.error_occurred.emit("BLE worker is not running")
            return None
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        future.add_done_callback(self._report_unhandled_error)
        return future

    def _report_unhandled_error(self, future: Future) -> None:
        error = future.exception()
        if error is not None:
            self.error_occurred.emit(f"BLE worker error: {error}")

    def stop(self) -> None:
        if not self._thread.is_alive():
            return
        self._stopping = True
        loop = self._loop
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._disconnect(), loop)
            try:
                future.result(timeout=3)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=3)
