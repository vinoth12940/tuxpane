import Foundation

public final class MachineStore {
    public private(set) var machines: [Machine]
    private let defaults: UserDefaults
    private let secrets: SecretStore
    private let key = "machines"

    public init(defaults: UserDefaults, secrets: SecretStore) {
        self.defaults = defaults
        self.secrets = secrets
        machines = defaults.data(forKey: key).flatMap { try? JSONDecoder().decode([Machine].self, from: $0) } ?? []
    }
    @discardableResult public func add(_ pairing: PairingInfo) throws -> Machine {
        let machine: Machine
        // Same certificate, or (after `tuxpane pair --reset` / a reinstall) same name and a shared address.
        if let index = machines.firstIndex(where: {
            $0.fingerprint == pairing.fingerprint
                || ($0.name == pairing.name && !Set($0.hosts).isDisjoint(with: pairing.hosts))
        }) {
            machine = Machine(id: machines[index].id, pairing: pairing, preset: machines[index].preset)
            machines[index] = machine
        } else {
            machine = Machine(pairing: pairing)
            machines.append(machine)
        }
        try secrets.setSecret(pairing.token, for: machine.id.uuidString)
        save()
        return machine
    }
    public func update(_ machine: Machine) {
        guard let index = machines.firstIndex(where: { $0.id == machine.id }) else { return }
        machines[index] = machine
        save()
    }
    public func remove(_ id: UUID) {
        machines.removeAll { $0.id == id }
        secrets.deleteSecret(for: id.uuidString)
        save()
    }
    public func token(for machine: Machine) -> String? { secrets.secret(for: machine.id.uuidString) }
    private func save() { defaults.set(try? JSONEncoder().encode(machines), forKey: key) }
}
