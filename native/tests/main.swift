import Foundation

let cases: [(String, NavigationPolicy.Destination)] = [
    ("https://app.droprate.co.uk/app", .hub),
    ("https://app.droprate.co.uk/owner#scan", .hub),
    ("https://app.droprate.co.uk/founders", .hub),
    ("https://app.droprate.co.uk:443/app", .hub),
    ("https://app.droprate.co.uk:444/app", .browser),
    ("https://app.droprate.co.uk.evil.test/", .browser),
    ("https://droprate.co.uk/", .browser),
    ("https://user:password@app.droprate.co.uk/", .blocked),
    ("http://app.droprate.co.uk/", .blocked),
    ("javascript:alert(1)", .blocked),
    ("file:///etc/passwd", .blocked),
    ("intent://camera", .blocked)
]
for (value, expected) in cases {
    precondition(NavigationPolicy.destination(URL(string: value)!) == expected, value)
}
print("Passed \(cases.count) native navigation policy cases.")
