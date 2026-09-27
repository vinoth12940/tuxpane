import Darwin
import Foundation
import TuxPaneCore

/// Broadcasts a discovery query once a second and collects replies from Linux machines in pairing mode.
final class DiscoveryBrowser {
    var onChange: (([DiscoveredMachine]) -> Void)?
    var machines: [DiscoveredMachine] { list.machines }
    private var list = DiscoveryList()
    private var socketFD: Int32 = -1
    private var source: DispatchSourceRead?
    private var timer: Timer?

    func start() {
        guard socketFD < 0 else { return }
        list = DiscoveryList()
        onChange?([])
        socketFD = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard socketFD >= 0 else { return }
        var enable: Int32 = 1
        setsockopt(socketFD, SOL_SOCKET, SO_BROADCAST, &enable, socklen_t(MemoryLayout<Int32>.size))
        _ = fcntl(socketFD, F_SETFL, fcntl(socketFD, F_GETFL) | O_NONBLOCK)
        let fd = socketFD
        let source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: .main)
        source.setEventHandler { [weak self] in self?.readReplies() }
        source.setCancelHandler { close(fd) }  // closing earlier could let a reused fd number reach a stale source
        source.resume()
        self.source = source
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.sendQuery() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        sendQuery()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        if let source {
            source.cancel()
        } else if socketFD >= 0 {
            close(socketFD)
        }
        source = nil
        socketFD = -1
    }

    deinit { stop() }

    private static func now() -> TimeInterval { ProcessInfo.processInfo.systemUptime }

    /// The limited broadcast plus every up, non-loopback IPv4 interface's broadcast address.
    private func broadcastAddresses() -> [in_addr] {
        var addresses = [in_addr(s_addr: INADDR_BROADCAST)]
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0, let first = list else { return addresses }
        defer { freeifaddrs(list) }
        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let entry = cursor?.pointee {
            let flags = Int32(entry.ifa_flags)
            if flags & IFF_UP != 0, flags & IFF_BROADCAST != 0, flags & IFF_LOOPBACK == 0,
                let broadcast = entry.ifa_dstaddr, broadcast.pointee.sa_family == sa_family_t(AF_INET)
            {
                let address = broadcast.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr }
                addresses.append(address)
            }
            cursor = entry.ifa_next
        }
        return addresses
    }

    private func sendQuery() {
        guard socketFD >= 0 else { return }
        if list.prune(at: Self.now()) { onChange?(list.machines) }
        for address in broadcastAddresses() {
            var target = sockaddr_in()
            target.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            target.sin_family = sa_family_t(AF_INET)
            target.sin_port = PairingProtocol.port.bigEndian
            target.sin_addr = address
            Discovery.query.withUnsafeBytes { bytes in
                withUnsafePointer(to: &target) {
                    $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                        _ = sendto(
                            socketFD, bytes.baseAddress, bytes.count, 0, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
        }
    }

    private func readReplies() {
        var buffer = [UInt8](repeating: 0, count: 2048)
        while true {
            var from = sockaddr_in()
            var length = socklen_t(MemoryLayout<sockaddr_in>.size)
            let count = withUnsafeMutablePointer(to: &from) {
                $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                    recvfrom(socketFD, &buffer, buffer.count, 0, $0, &length)
                }
            }
            guard count > 0 else { return }
            let host = String(cString: inet_ntoa(from.sin_addr))
            guard let machine = Discovery.parseReply(Data(buffer[0..<count]), from: host) else { continue }
            if list.saw(machine, at: Self.now()) { onChange?(list.machines) }
        }
    }
}
