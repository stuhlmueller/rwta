import Foundation
import CoreLocation
import AppKit

/// Top-level event sent from the Python backend over stdout.
/// Each line is one JSON object with either an `event` field (notification)
/// or an `id` field (response to a numbered request).
struct ServerMessage: Decodable {
    var event: String?
    var id: Int?
    var result: AnyCodable?
    var error: String?
    var rawJSON: [String: AnyCodable]

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode([String: AnyCodable].self)
        self.rawJSON = raw
        self.event = raw["event"]?.value as? String
        self.id = raw["id"]?.value as? Int
        if let inner = raw["result"] {
            self.result = inner
        }
        if let err = raw["error"]?.value as? String {
            self.error = err
        }
    }
}

/// A small type-erased JSON value so we can pass arbitrary nested payloads
/// through `ServerMessage.rawJSON` and decode the relevant slice on demand.
struct AnyCodable: Codable {
    let value: Any

    init(_ value: Any) { self.value = value }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self.value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            self.value = bool
        } else if let int = try? container.decode(Int.self) {
            self.value = int
        } else if let double = try? container.decode(Double.self) {
            self.value = double
        } else if let string = try? container.decode(String.self) {
            self.value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            self.value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            self.value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Unsupported JSON value"
            )
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case is NSNull:
            try container.encodeNil()
        case let v as Bool:
            try container.encode(v)
        case let v as Int:
            try container.encode(v)
        case let v as Double:
            try container.encode(v)
        case let v as String:
            try container.encode(v)
        case let v as [Any]:
            try container.encode(v.map { AnyCodable($0) })
        case let v as [String: Any]:
            try container.encode(v.mapValues { AnyCodable($0) })
        default:
            throw EncodingError.invalidValue(
                value,
                EncodingError.Context(codingPath: container.codingPath,
                                      debugDescription: "Unsupported type: \(type(of: value))")
            )
        }
    }
}

/// Convenience helpers to pull typed fields out of an AnyCodable dict.
extension Dictionary where Key == String, Value == AnyCodable {
    func string(_ key: String) -> String? { self[key]?.value as? String }
    func int(_ key: String) -> Int? { self[key]?.value as? Int }
    func double(_ key: String) -> Double? {
        if let d = self[key]?.value as? Double { return d }
        if let i = self[key]?.value as? Int { return Double(i) }
        return nil
    }
    func bool(_ key: String) -> Bool? { self[key]?.value as? Bool }
    func array(_ key: String) -> [AnyCodable]? {
        guard let raw = self[key]?.value as? [Any] else { return nil }
        return raw.map { AnyCodable($0) }
    }
}

/// The player's current geographic position, used by the map.
struct GameLocation: Equatable {
    var city: String
    var region: String
    var country: String
    var address: String?
    var coordinate: CLLocationCoordinate2D?
    var gameTime: String?
    var weather: String?
    var saveName: String?

    var displayName: String {
        if let address, !address.isEmpty { return address }
        return [city, region, country].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    static func == (lhs: GameLocation, rhs: GameLocation) -> Bool {
        lhs.city == rhs.city
            && lhs.region == rhs.region
            && lhs.country == rhs.country
            && lhs.address == rhs.address
            && lhs.gameTime == rhs.gameTime
            && lhs.weather == rhs.weather
            && lhs.saveName == rhs.saveName
            && lhs.coordinate?.latitude == rhs.coordinate?.latitude
            && lhs.coordinate?.longitude == rhs.coordinate?.longitude
    }
}

/// One entry in the visible chat history.
struct ChatTurn: Identifiable, Equatable {
    enum Role { case user, narrator, system }
    let id = UUID()
    var role: Role
    var text: String
    var timestamp: Date = Date()
}

/// One selectable generated-image style.
struct ImageStyleChoice: Identifiable, Equatable {
    var id: String
    var name: String
}

/// One cached generated scene image for this run.
struct SceneImageEntry: Identifiable, Equatable {
    var id: String
    var turnIndex: Int
    var styleID: String
    var styleName: String
    var path: String
    var prompt: String
    var createdAt: String
    var image: NSImage?

    static func == (lhs: SceneImageEntry, rhs: SceneImageEntry) -> Bool {
        lhs.id == rhs.id
            && lhs.turnIndex == rhs.turnIndex
            && lhs.styleID == rhs.styleID
            && lhs.styleName == rhs.styleName
            && lhs.path == rhs.path
            && lhs.prompt == rhs.prompt
            && lhs.createdAt == rhs.createdAt
    }
}

/// Saved game metadata.
struct SaveEntry: Identifiable, Decodable, Equatable {
    var name: String
    var updated_at: String
    var path: String
    var previewImagePath: String?
    var previewStyleName: String?
    var id: String { name }
}
