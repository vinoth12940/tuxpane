import XCTest

@testable import TuxPaneCore

final class DiscoveryTests: XCTestCase {
    func testQueryMatchesTheAgent() throws {
        let object = try JSONSerialization.jsonObject(with: Discovery.query) as? [String: Any]
        XCTAssertEqual(object?["q"] as? String, "tuxpane-discover")
        XCTAssertEqual(object?["v"] as? Int, 1)
    }

    func testParsesReplies() {
        let reply = Data(#"{"n":"box","os":"Linux Mint 22.3","v":1,"pp":7301}"#.utf8)
        XCTAssertEqual(
            Discovery.parseReply(reply, from: "192.168.1.20"),
            DiscoveredMachine(name: "box", os: "Linux Mint 22.3", host: "192.168.1.20", pairingPort: 7301))
        XCTAssertNil(Discovery.parseReply(Data("junk".utf8), from: "192.168.1.20"))
        XCTAssertNil(Discovery.parseReply(reply, from: "8.8.8.8"), "replies must come from a private address")
        XCTAssertNil(Discovery.parseReply(Data(#"{"n":"box","v":2,"pp":7301}"#.utf8), from: "192.168.1.20"))
    }

    func testListDropsMachinesThatStopAnsweringAndMergesByName() {
        var list = DiscoveryList(expiry: 3)
        let wifi = DiscoveredMachine(name: "box", os: "Mint", host: "192.168.1.30", pairingPort: 7301)
        let ethernet = DiscoveredMachine(name: "box", os: "Mint", host: "192.168.1.20", pairingPort: 7301)
        XCTAssertTrue(list.saw(wifi, at: 0))
        XCTAssertFalse(list.saw(ethernet, at: 1), "the same machine on a second interface is not a new entry")
        XCTAssertEqual(list.machines.map(\.host), ["192.168.1.30"])
        XCTAssertFalse(list.prune(at: 3.5), "still answering through its second address")
        XCTAssertTrue(list.prune(at: 10))
        XCTAssertTrue(list.machines.isEmpty)
    }
}
