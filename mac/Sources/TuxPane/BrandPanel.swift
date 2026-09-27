import AppKit
import SwiftUI
import TuxPaneCore

/// The dark branded column shared by the setup and machines windows.
struct BrandPanel<Footer: View>: View {
    var current: SetupStep?
    @ViewBuilder var footer: Footer

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 76, height: 76)
                .shadow(color: .black.opacity(0.45), radius: 13, y: 8)
            VStack(alignment: .leading, spacing: 4) {
                Text("TuxPane").font(.system(size: 22, weight: .bold))
                Text("Your Linux desktop,\nright on your Mac.").font(.system(size: 13)).opacity(0.72)
            }
            if let current {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(SetupStep.allCases, id: \.self) { step in
                        StepRow(step: step, progress: step.state(current: current))
                    }
                }
                .padding(.top, 12)
            }
            Spacer(minLength: 0)
            footer
            Text("Version \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")")
                .font(.system(size: 11)).opacity(0.4)
        }
        .foregroundStyle(.white)
        .padding(EdgeInsets(top: 44, leading: 24, bottom: 20, trailing: 18))
        .frame(width: 236, alignment: .leading)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(BrandBackground())
    }
}

extension BrandPanel where Footer == EmptyView {
    init(current: SetupStep?) { self.init(current: current) { EmptyView() } }
}

struct BrandBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.106, green: 0.125, blue: 0.188), Color(red: 0.043, green: 0.051, blue: 0.078)],
                startPoint: .topLeading, endPoint: .bottomTrailing)
            RadialGradient(
                colors: [Color(red: 0.35, green: 0.47, blue: 1).opacity(0.38), .clear],
                center: UnitPoint(x: 0.2, y: 0), startRadius: 0, endRadius: 260)
            RadialGradient(
                colors: [Color(red: 0.24, green: 0.78, blue: 0.67).opacity(0.18), .clear],
                center: UnitPoint(x: 1, y: 1), startRadius: 0, endRadius: 220)
        }
    }
}

private struct StepRow: View {
    let step: SetupStep
    let progress: SetupStep.Progress

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                switch progress {
                case .done:
                    Circle().fill(Color(red: 0.19, green: 0.70, blue: 0.35))
                    Image(systemName: "checkmark").font(.system(size: 10, weight: .bold))
                case .current:
                    Circle().strokeBorder(.white, lineWidth: 2)
                case .upcoming:
                    Circle().strokeBorder(.white.opacity(0.35), lineWidth: 1.5)
                    Text("\(step.rawValue)").font(.system(size: 10, weight: .bold))
                }
            }
            .frame(width: 20, height: 20)
            Text(step.title).font(.system(size: 13, weight: progress == .current ? .semibold : .regular))
        }
        .opacity(progress == .upcoming ? 0.55 : 1)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(step.title), \(progress == .done ? "done" : progress == .current ? "current step" : "next")")
    }
}

/// Title, subtitle, content and a bottom action row: the right-hand side of every setup page.
struct SetupPage<Content: View, Actions: View>: View {
    let title: String
    var subtitle: String? = nil
    @ViewBuilder var content: Content
    @ViewBuilder var actions: Actions

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(title).font(.system(size: 23, weight: .semibold))
            if let subtitle {
                Text(subtitle).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            content
            Spacer(minLength: 0)
            HStack(spacing: 10) { actions }
        }
        .padding(EdgeInsets(top: 44, leading: 32, bottom: 24, trailing: 32))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}
