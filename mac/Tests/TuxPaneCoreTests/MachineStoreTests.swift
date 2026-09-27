import XCTest
@testable import TuxPaneCore

private let fp = String(repeating: "c", count: 64)
private func info(_ name: String = "box", token: String = "token-token-token-1", fingerprint: String = fp)
    -> PairingInfo
{
    PairingInfo(name: name, hosts: ["192.168.1.20"], port: 7300, token: token, fingerprint: fingerprint)
}

final class MachineStoreTests: XCTestCase {
    private var defaults: UserDefaults!
    private let secrets = InMemorySecretStore()
    override func setUp() { defaults = UserDefaults(suiteName: "tuxpane-tests-\(UUID().uuidString)") }
    func testAddPersistsMachineAndKeepsTokenOutOfDefaults() throws {
        let machine = try MachineStore(defaults: defaults, secrets: secrets).add(info())
        let reloaded = MachineStore(defaults: defaults, secrets: secrets)
        XCTAssertEqual(reloaded.machines, [machine])
        XCTAssertEqual(reloaded.token(for: machine), "token-token-token-1")
        XCTAssertFalse(
            String(decoding: defaults.data(forKey: "machines") ?? Data(), as: UTF8.self).contains("token-token-token-1")
        )
    }
    func testPairingTheSameMachineAgainReplacesIt() throws {
        let store = MachineStore(defaults: defaults, secrets: secrets)
        let first = try store.add(info())
        let second = try store.add(info("box-renamed", token: "token-token-token-2"))
        XCTAssertEqual(store.machines.map(\.id), [first.id])
        XCTAssertEqual(store.machines[0].name, "box-renamed")
        XCTAssertEqual(store.token(for: second), "token-token-token-2")
    }
    func testUpdateAndRemove() throws {
        let store = MachineStore(defaults: defaults, secrets: secrets)
        var machine = try store.add(info())
        machine.preset = .fast
        store.update(machine)
        XCTAssertEqual(MachineStore(defaults: defaults, secrets: secrets).machines[0].preset, .fast)
        store.remove(machine.id)
        XCTAssertTrue(store.machines.isEmpty)
        XCTAssertNil(secrets.secret(for: machine.id.uuidString))
    }
    func testResolutionPresetsFollowTheMacScreen() {
        let pro16 = CGSize(width: 3456, height: 2160)
        XCTAssertTrue(ResolutionPreset.balanced.size(forScreenPixels: pro16) == (2560, 1600))
        XCTAssertTrue(ResolutionPreset.fast.size(forScreenPixels: pro16) == (1920, 1200))
        XCTAssertTrue(ResolutionPreset.sharp.size(forScreenPixels: pro16) == (3456, 2160))
        XCTAssertTrue(
            ResolutionPreset.balanced.size(forScreenPixels: CGSize(width: 1920, height: 1080)) == (1920, 1080))
    }

    func testRePairingAfterAResetUpdatesTheSameMachine() throws {
        let store = MachineStore(defaults: defaults, secrets: secrets)
        let original = try store.add(info())
        let rePaired = try store.add(
            PairingInfo(
                name: "box", hosts: ["192.168.1.20", "100.64.100.27"], port: 7300,
                token: "token-token-token-9", fingerprint: String(repeating: "d", count: 64)))
        XCTAssertEqual(store.machines.map(\.id), [original.id])
        XCTAssertEqual(store.machines[0].fingerprint, String(repeating: "d", count: 64))
        XCTAssertEqual(store.token(for: rePaired), "token-token-token-9")
    }

    func testDifferentMachinesWithTheSameNameStaySeparate() throws {
        let store = MachineStore(defaults: defaults, secrets: secrets)
        try store.add(info())
        try store.add(
            PairingInfo(
                name: "box", hosts: ["10.0.0.9"], port: 7300, token: "token-token-token-3",
                fingerprint: String(repeating: "e", count: 64)))
        XCTAssertEqual(store.machines.count, 2)
    }
}
