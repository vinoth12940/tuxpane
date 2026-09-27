import AVFoundation
import CoreMedia
import TuxPaneCore

/// Hardware-decodes HEVC access units (VideoToolbox via AVSampleBufferDisplayLayer) and shows each immediately.
final class VideoRenderer {
    let layer = AVSampleBufferDisplayLayer()
    var onNeedKeyframe: (() -> Void)?

    private var format: CMVideoFormatDescription?
    private var parameterSets: [Data] = []
    private var waitingForKeyframe = true
    private var lastKeyframeRequest = Date.distantPast
    private(set) var framesEnqueued = 0
    var failed: Bool { layer.sampleBufferRenderer.status == .failed }

    init() {
        layer.videoGravity = .resizeAspect
        layer.backgroundColor = CGColor(gray: 0, alpha: 1)
    }

    func reset() {
        waitingForKeyframe = true
        layer.sampleBufferRenderer.flush()
    }

    func enqueue(nals: [Data], keyframe: Bool) {
        let parts = HEVC.split(nals)
        if let vps = parts.vps, let sps = parts.sps, let pps = parts.pps, [vps, sps, pps] != parameterSets {
            format = Self.makeFormat(vps: vps, sps: sps, pps: pps)
            parameterSets = [vps, sps, pps]
        }
        let renderer = layer.sampleBufferRenderer
        if renderer.status == .failed || renderer.requiresFlushToResumeDecoding {
            renderer.flush()
            waitingForKeyframe = true
        }
        if waitingForKeyframe {
            guard keyframe, format != nil else {
                requestKeyframe()
                return
            }
            waitingForKeyframe = false
        }
        guard let format, !parts.frame.isEmpty,
            let sample = Self.makeSample(HEVC.lengthPrefixed(parts.frame), format: format)
        else { return }
        renderer.enqueue(sample)
        framesEnqueued += 1
    }

    private func requestKeyframe() {
        guard Date().timeIntervalSince(lastKeyframeRequest) > 1 else { return }
        lastKeyframeRequest = Date()
        onNeedKeyframe?()
    }

    private static func makeFormat(vps: Data, sps: Data, pps: Data) -> CMVideoFormatDescription? {
        let sets = [vps, sps, pps].map { [UInt8]($0) }
        var format: CMVideoFormatDescription?
        let status = sets[0].withUnsafeBufferPointer { v in
            sets[1].withUnsafeBufferPointer { s in
                sets[2].withUnsafeBufferPointer { p in
                    CMVideoFormatDescriptionCreateFromHEVCParameterSets(
                        allocator: kCFAllocatorDefault, parameterSetCount: 3,
                        parameterSetPointers: [v.baseAddress!, s.baseAddress!, p.baseAddress!],
                        parameterSetSizes: sets.map(\.count), nalUnitHeaderLength: 4,
                        extensions: nil, formatDescriptionOut: &format)
                }
            }
        }
        return status == noErr ? format : nil
    }

    private static func makeSample(_ data: Data, format: CMVideoFormatDescription) -> CMSampleBuffer? {
        var block: CMBlockBuffer?
        guard
            CMBlockBufferCreateWithMemoryBlock(
                allocator: kCFAllocatorDefault, memoryBlock: nil, blockLength: data.count,
                blockAllocator: kCFAllocatorDefault, customBlockSource: nil, offsetToData: 0,
                dataLength: data.count, flags: kCMBlockBufferAssureMemoryNowFlag, blockBufferOut: &block
            ) == kCMBlockBufferNoErr, let block
        else { return nil }
        let copied = data.withUnsafeBytes {
            CMBlockBufferReplaceDataBytes(
                with: $0.baseAddress!, blockBuffer: block, offsetIntoDestination: 0, dataLength: data.count)
        }
        guard copied == kCMBlockBufferNoErr else { return nil }
        var sample: CMSampleBuffer?
        var size = data.count
        guard
            CMSampleBufferCreateReady(
                allocator: kCFAllocatorDefault, dataBuffer: block, formatDescription: format, sampleCount: 1,
                sampleTimingEntryCount: 0, sampleTimingArray: nil, sampleSizeEntryCount: 1,
                sampleSizeArray: &size, sampleBufferOut: &sample
            ) == noErr, let sample
        else { return nil }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
            CFArrayGetCount(attachments) > 0
        {
            let dict = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(
                dict,
                Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return sample
    }
}
