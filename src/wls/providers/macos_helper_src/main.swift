// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 서민재
//
// Wireless Lab helper for macOS.
//
// macOS gives Wi-Fi network names (SSID) and BSSIDs only to an application
// bundle that the user allowed to use Location Services. This small app is
// that bundle. It does nothing with the location itself and sends nothing
// anywhere; it only prints Wi-Fi information as JSON for Wireless Lab.
//
//   WirelessLabHelper authorize   ask for the permission (run through `open`)
//   WirelessLabHelper status      {"location": "..."}
//   WirelessLabHelper link        current connection
//   WirelessLabHelper scan        nearby networks
//   WirelessLabHelper bluetooth N nearby Bluetooth devices, listening N seconds

import AppKit
import CoreBluetooth
import CoreLocation
import CoreWLAN
import Foundation

// One manager for the whole process. A fresh manager reports "not determined"
// until the system has told it the real state, so commands wait for that first.
final class LocationState: NSObject, CLLocationManagerDelegate {
    let manager = CLLocationManager()
    var known = false

    override init() {
        super.init()
        manager.delegate = self
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        known = true
        onChange?()
    }

    var onChange: (() -> Void)?

    /// Let the run loop turn until the state is known (or a short time passed).
    func waitUntilKnown(seconds: Double = 3.0) {
        let deadline = Date().addingTimeInterval(seconds)
        while !known && Date() < deadline {
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
        }
    }
}

let location = LocationState()

func locationStatus() -> String {
    guard CLLocationManager.locationServicesEnabled() else { return "services_off" }
    switch location.manager.authorizationStatus {
    case .notDetermined: return "not_determined"
    case .denied: return "denied"
    case .restricted: return "restricted"
    default: return "authorized"
    }
}

func emit(_ object: [String: Any]) {
    var out = object
    out["helper"] = 2  // raised when commands are added; the caller rebuilds an older helper
    out["location"] = locationStatus()
    let data = try! JSONSerialization.data(withJSONObject: out, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

func channelInfo(_ channel: CWChannel?) -> [String: Any] {
    guard let channel = channel else { return [:] }
    return [
        "channel": channel.channelNumber,
        "band": channel.channelBand.rawValue,
        "width": channel.channelWidth.rawValue,
    ]
}

func wifiInterface(_ name: String?) -> CWInterface? {
    let client = CWWiFiClient.shared()
    if let name = name, !name.isEmpty { return client.interface(withName: name) }
    return client.interface()
}

func link(_ interfaceName: String?) {
    guard let interface = wifiInterface(interfaceName) else {
        emit(["error": "no Wi-Fi interface"])
        return
    }
    var out: [String: Any] = channelInfo(interface.wlanChannel())
    out["power"] = interface.powerOn()
    out["rssi"] = interface.rssiValue()
    out["noise"] = interface.noiseMeasurement()
    out["tx_rate"] = interface.transmitRate()
    out["ssid"] = interface.ssid() ?? NSNull()
    out["bssid"] = interface.bssid() ?? NSNull()
    emit(out)
}

func scan(_ interfaceName: String?) {
    guard let interface = wifiInterface(interfaceName) else {
        emit(["error": "no Wi-Fi interface"])
        return
    }
    do {
        let found = try interface.scanForNetworks(withName: nil)
        let networks: [[String: Any]] = found.map { network in
            var out = channelInfo(network.wlanChannel)
            out["rssi"] = network.rssiValue
            out["ssid"] = network.ssid ?? NSNull()
            out["bssid"] = network.bssid ?? NSNull()
            out["security"] = (0...13).filter { code in
                guard let security = CWSecurity(rawValue: code) else { return false }
                return network.supportsSecurity(security)
            }
            return out
        }
        emit(["networks": networks])
    } catch {
        emit(["error": "scan failed: \(error.localizedDescription)"])
    }
}

final class BluetoothScan: NSObject, CBCentralManagerDelegate {
    var central: CBCentralManager!
    var found: [UUID: [String: Any]] = [:]
    var stateKnown = false

    override init() {
        super.init()
        central = CBCentralManager(
            delegate: self, queue: nil, options: [CBCentralManagerOptionShowPowerAlertKey: false])
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .unknown, .resetting: return
        default: stateKnown = true
        }
        if central.state == .poweredOn {
            central.scanForPeripherals(
                withServices: nil, options: [CBCentralManagerScanOptionAllowDuplicatesKey: true])
        }
    }

    func centralManager(
        _ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any], rssi RSSI: NSNumber
    ) {
        let rssi = RSSI.intValue
        if rssi >= 0 { return }  // 127 means "not available"
        var entry = found[peripheral.identifier] ?? ["id": peripheral.identifier.uuidString, "seen": 0]
        entry["rssi"] = max(rssi, entry["rssi"] as? Int ?? -200)
        entry["seen"] = (entry["seen"] as? Int ?? 0) + 1
        if let name = (advertisementData[CBAdvertisementDataLocalNameKey] as? String) ?? peripheral.name {
            entry["name"] = name
        }
        if let connectable = advertisementData[CBAdvertisementDataIsConnectable] as? NSNumber {
            entry["connectable"] = connectable.boolValue
        }
        if let data = advertisementData[CBAdvertisementDataManufacturerDataKey] as? Data {
            let bytes = [UInt8](data)
            if bytes.count >= 2 { entry["company"] = Int(bytes[0]) | (Int(bytes[1]) << 8) }
        }
        if let services = advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] {
            entry["services"] = services.map { $0.uuidString }
        }
        found[peripheral.identifier] = entry
    }

    var stateName: String {
        switch central.state {
        case .poweredOn: return "on"
        case .poweredOff: return "off"
        case .unauthorized: return "unauthorized"
        case .unsupported: return "unsupported"
        default: return "unknown"
        }
    }
}

func spin(seconds: Double, until done: () -> Bool = { false }) {
    let deadline = Date().addingTimeInterval(seconds)
    while !done() && Date() < deadline {
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05))
    }
}

func bluetooth(seconds: Double) {
    // The first use shows the macOS permission question; give the user time to answer.
    let asking = CBCentralManager.authorization == .notDetermined
    let scan = BluetoothScan()
    spin(seconds: asking ? 120 : 5, until: { scan.stateKnown })
    if scan.central.state == .poweredOn {
        spin(seconds: seconds)
        scan.central.stopScan()
    }
    emit(["bluetooth": scan.stateName, "devices": Array(scan.found.values)])
}

final class Authorizer: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        location.waitUntilKnown()
        if locationStatus() == "not_determined" {
            location.onChange = { if locationStatus() != "not_determined" { self.finish() } }
            NSApp.activate(ignoringOtherApps: true)
            location.manager.requestWhenInUseAuthorization()
            // Give the user time to answer; quit by ourselves otherwise.
            DispatchQueue.main.asyncAfter(deadline: .now() + 120) { self.finish() }
        } else {
            finish()
        }
    }

    func finish() {
        emit([:])
        NSApp.terminate(nil)
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
let command = arguments.first ?? "authorize"
let interfaceName = arguments.count > 1 ? arguments[1] : nil

if command != "authorize" { location.waitUntilKnown() }

switch command {
case "status":
    emit([:])
case "link":
    link(interfaceName)
case "scan":
    scan(interfaceName)
case "bluetooth":
    bluetooth(seconds: min(max(Double(interfaceName ?? "") ?? 5, 1), 30))
default:
    let app = NSApplication.shared
    let authorizer = Authorizer()
    app.delegate = authorizer
    app.setActivationPolicy(.accessory)
    app.run()
}
