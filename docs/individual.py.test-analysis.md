# Test Analysis for `individual.py`

## Current Test Coverage
- ✅ `construct_jql()` - Basic tests exist (team, project, error cases)
- ❌ All other functions are untested

## Recommended Test Areas (Priority Order)

### 1. **High Priority - Pure Functions (Easy to Test, High Value)**

#### `transform_month(month)` (Line 272-275)
- **Why**: Pure function, no dependencies, simple logic
- **Test Cases**:
  - Valid month formats: "2024-01", "2024-12"
  - Edge cases: "2024-02" (February), "2024-03" (March)
  - Verify correct month abbreviation mapping
- **Expected Coverage Gain**: ~3 lines, minimal but easy win

#### `calculate_points(issue)` (Line 71-73)
- **Why**: Simple logic, but handles None/0 cases
- **Test Cases**:
  - Issue with points value
  - Issue with None points (should return 0)
  - Issue with 0 points
- **Expected Coverage Gain**: ~3 lines, easy to test

#### `print_year_summary(assignee_metrics)` (Line 323-356)
- **Why**: Pure aggregation logic, no external dependencies
- **Test Cases**:
  - Empty assignee_metrics (should print "No tickets found")
  - Single month, single team, single assignee
  - Multiple months, multiple teams, multiple assignees
  - Verify correct aggregation (totals and per-person)
  - Verify sorting by ticket count descending
- **Expected Coverage Gain**: ~34 lines, significant coverage boost
- **Note**: Use `@patch('builtins.print')` to avoid console output

### 2. **Medium Priority - Complex Logic Functions**

#### `calculate_rolling_top_contributors(assignee_metrics, end_date)` (Line 170-245)
- **Why**: Complex aggregation and ratio calculation logic
- **Test Cases**:
  - Empty assignee_metrics
  - Single month with single assignee
  - Multiple months (last 3 months)
  - Multiple assignees with different ratios
  - Verify correct calculation of:
    - Total metrics per assignee
    - Monthly ratios (points and tickets)
    - Average ratios over active months
    - Top 3 contributors for each category:
      - points_ratio
      - tickets_ratio
      - points_total
      - tickets_total
  - Edge case: assignees with 0 points/tickets
  - Edge case: months_active counting
- **Expected Coverage Gain**: ~75 lines, significant coverage boost
- **Complexity**: Medium - requires careful mock data setup

#### `process_and_display_metrics(metrics_per_month, assignee_metrics)` (Line 139-166)
- **Why**: Display logic with calculations (averages, ratios)
- **Test Cases**:
  - Empty metrics
  - Single month, single team, single assignee
  - Multiple months, teams, assignees
  - Verify correct calculation of:
    - Team averages (points and tickets per member)
    - Individual ratios (points_ratio, tickets_ratio)
  - Verify sorting by points descending
  - Edge case: team_size = 0 (division by zero protection)
- **Expected Coverage Gain**: ~28 lines
- **Note**: Use `@patch('builtins.print')` to avoid console output

### 3. **Lower Priority - I/O and Integration Functions**

#### `write_csv(assignee_metrics, output_file)` (Line 278-320)
- **Why**: File I/O, can be tested with temp files
- **Test Cases**:
  - Empty assignee_metrics
  - Single month, single assignee
  - Multiple months, multiple assignees
  - Verify CSV structure:
    - Header rows (Points and Tickets sections)
    - Correct month transformation
    - Correct data aggregation across teams
  - Verify file is created and contains expected data
- **Expected Coverage Gain**: ~42 lines
- **Note**: Use `tempfile` module for file operations

#### `construct_jql()` - Additional Edge Cases (Line 249-269)
- **Why**: Already has basic tests, but could test more edge cases
- **Additional Test Cases**:
  - Custom completion statuses (not just "released", "done")
  - Projects with special characters or quotes
  - Status names with spaces (e.g., "To Release")
  - Verify status.title() casing behavior
- **Expected Coverage Gain**: ~5-10 lines

### 4. **Low Priority - Integration Functions (Harder to Test)**

#### `calculate_individual_jira_metrics()` (Line 77-135)
- **Why**: Heavy external dependencies (Jira API), complex integration
- **Test Strategy**: 
  - Mock `get_tickets_from_jira()`, `extract_status_timestamps()`, `interpret_status_timestamps()`
  - Test aggregation logic with mock tickets
  - Test edge cases: no tickets, no completion timestamps, unassigned tickets
- **Expected Coverage Gain**: ~58 lines
- **Complexity**: High - requires extensive mocking
- **Recommendation**: Test after simpler functions are covered

## Estimated Coverage Impact

| Function | Lines | Priority | Estimated Coverage Gain |
|----------|-------|----------|------------------------|
| `transform_month()` | 4 | High | ~3 lines |
| `calculate_points()` | 3 | High | ~3 lines |
| `print_year_summary()` | 34 | High | ~34 lines |
| `calculate_rolling_top_contributors()` | 75 | Medium | ~75 lines |
| `process_and_display_metrics()` | 28 | Medium | ~28 lines |
| `write_csv()` | 42 | Lower | ~42 lines |
| `construct_jql()` (additional) | 20 | Lower | ~5-10 lines |
| **Total** | | | **~200 lines** |

**Current Coverage**: 11% (254 lines total, ~28 lines covered)
**With Recommended Tests**: ~228 lines covered = **~90% coverage**

## Implementation Order

1. **Start with pure functions** (easiest, quick wins):
   - `transform_month()`
   - `calculate_points()`
   - `print_year_summary()`

2. **Then complex logic** (medium effort, high value):
   - `calculate_rolling_top_contributors()`
   - `process_and_display_metrics()`

3. **Finally I/O functions** (requires temp files):
   - `write_csv()`

4. **Optional integration tests** (if time permits):
   - `calculate_individual_jira_metrics()`

## Testing Patterns to Follow

- Use `unittest.mock.patch` for external dependencies
- Use `@patch('builtins.print')` for functions that print
- Use `tempfile` module for file I/O tests
- Follow existing test patterns in `test_individual.py`
- Use `MagicMock` for Jira issue objects
- Test edge cases: empty data, None values, division by zero
