import Foundation

/// The checks shown while pairing, so a failure points at the exact step that went wrong.
public struct PairingChecklist: Equatable {
    public enum Step: Int, CaseIterable {
        case reach, certificate, signIn, video

        public var title: String {
            switch self {
            case .reach: return "Reaching the machine"
            case .certificate: return "Checking its security certificate"
            case .signIn: return "Signing in"
            case .video: return "Receiving the picture"
            }
        }
    }

    public enum State: Equatable { case pending, running, done, failed }

    private var states: [Step: State] = [:]

    public init() {}

    public func state(_ step: Step) -> State { states[step] ?? .pending }

    public mutating func start() {
        states = [.reach: .running]
    }

    /// TLS is up: the machine answered and presented the pinned certificate.
    public mutating func secured() { advance(through: .certificate) }

    /// WELCOME arrived: the token was accepted.
    public mutating func signedIn() { advance(through: .signIn) }

    public mutating func receivedVideo() { advance(through: .video) }

    public mutating func failed(_ outcome: ConnectOutcome) {
        let step: Step
        switch outcome {
        case .connected: return
        case .unreachable: step = .reach
        case .certificateMismatch: step = .certificate
        case .authenticationFailed, .versionMismatch: step = .signIn
        case .captureFailed: step = .video
        case .serverError, .connectionLost, .replaced:
            step = Step.allCases.first { state($0) == .running } ?? .reach
        }
        for earlier in Step.allCases where earlier.rawValue < step.rawValue { states[earlier] = .done }
        states[step] = .failed
        for later in Step.allCases where later.rawValue > step.rawValue { states[later] = .pending }
    }

    private mutating func advance(through step: Step) {
        for done in Step.allCases where done.rawValue <= step.rawValue { states[done] = .done }
        if let next = Step(rawValue: step.rawValue + 1) { states[next] = .running }
    }
}
